# db_connection.py
import os
import pyodbc
import threading


class DatabaseConnection:
    # Porta TCP statica dell'istanza SQL (roghipsql01\emsreset ascolta su 1434).
    # Usata come fallback quando il servizio SQL Browser (UDP 1434) non e'
    # raggiungibile e l'istanza nominata "host\istanza" non puo' essere risolta.
    DEFAULT_INSTANCE_PORT = 1434
    # IP del server SQL, usato se il nome DNS non e' risolvibile dalla macchina
    # (es. kiosk che non usa il DNS di dominio). Sovrascrivibile con la chiave
    # 'server_ip' in config o con la variabile d'ambiente DB_SERVER_IP.
    DEFAULT_SERVER_IP = '10.140.1.4'

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.connection = None
        self._local = threading.local()
        self._connect_lock = threading.Lock()

    def _get_thread_connection(self):
        return getattr(self._local, 'connection', None)

    def _set_thread_connection(self, conn):
        self._local.connection = conn
        # Backward compatibility: some callers may still inspect this attribute.
        self.connection = conn

    def _close_connection_safely(self, conn):
        if not conn:
            return
        try:
            conn.close()
        except Exception:
            pass

    def _is_connection_alive(self, conn):
        """Verifica in modo leggero che la connessione sia ancora utilizzabile."""
        if conn is None:
            return False
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            return True
        except pyodbc.Error:
            return False
        except Exception:
            return False

    def _server_ip(self, config):
        return config.get('server_ip') or os.environ.get('DB_SERVER_IP') or self.DEFAULT_SERVER_IP

    def _resolve_server(self, config, force_port=False, use_ip=False):
        """Restituisce il valore da usare per SERVER=.

        Se in config e' presente 'port' (o la variabile d'ambiente DB_PORT),
        oppure force_port=True, converte 'host\\istanza' in 'host,porta' cosi'
        da non dipendere dal servizio SQL Browser.
        """
        server = str(config['server']).strip()
        port = config.get('port') or os.environ.get('DB_PORT')
        if use_ip:
            force_port = True
        if not port and not force_port:
            return server
        if ',' in server and not use_ip:
            return server  # porta gia' specificata
        if ',' in server:
            port = port or server.split(',', 1)[1].strip()
            server = server.split(',', 1)[0]
        host = server.split('\\', 1)[0]
        if use_ip:
            host = self._server_ip(config)
        return f"{host},{port or self.DEFAULT_INSTANCE_PORT}"

    def _build_connection_string(self, force_port=False, use_ip=False):
        config = self.config_manager.load_config()

        drivers = [
            'ODBC Driver 18 for SQL Server',
            'ODBC Driver 17 for SQL Server',
            'SQL Server',
            'SQL Server Native Client 11.0'
        ]

        driver = None
        available_drivers = pyodbc.drivers()
        for d in drivers:
            if d in available_drivers:
                driver = d
                break

        if driver is None:
            raise Exception("Nessun driver SQL Server trovato. Installa un driver ODBC per SQL Server.")

        # Nota: il timeout di login e' passato a pyodbc.connect(timeout=...);
        # "Connection Timeout" non e' un attributo ODBC valido e generava
        # l'avviso "Invalid connection string attribute".
        return (
            f"DRIVER={{{driver}}};"
            f"SERVER={self._resolve_server(config, force_port, use_ip)};"
            f"DATABASE={config['database']};"
            f"UID={config['username']};"
            f"PWD={config['password']};"
            "Trusted_Connection=no;"
            "TrustServerCertificate=yes;"
            "Encrypt=yes;"
            "ConnectRetryCount=1;"
            "ConnectRetryInterval=5;"
            "Mars_Connection=yes;"
        )

    def _create_new_connection(self):
        # Tentativi in ordine:
        # 1) configurazione cosi' com'e' (host\istanza)
        # 2) host,porta  -> se SQL Browser non e' raggiungibile
        # 3) IP,porta    -> se il nome DNS non e' risolvibile
        attempts = [
            ({}, None),
            ({'force_port': True}, "Istanza SQL non risolta via SQL Browser, ritento con host,porta..."),
            ({'use_ip': True}, "Nome server non risolvibile (DNS), ritento con IP,porta..."),
        ]
        retryable = (
            'Error Locating Server/Instance', 'xFFFFFFFF',  # SQL Browser
            'No such host is known', '11001',               # DNS
        )
        conn = None
        last_error = None
        tried = set()
        for kwargs, message in attempts:
            conn_str = self._build_connection_string(**kwargs)
            if conn_str in tried:
                continue
            tried.add(conn_str)
            if message:
                print(message)
            try:
                conn = pyodbc.connect(conn_str, timeout=8)
                break
            except pyodbc.Error as e:
                last_error = e
                if not any(token in str(e) for token in retryable):
                    raise
        if conn is None:
            raise last_error
        conn.autocommit = True
        conn.timeout = 15  # timeout per ogni singola query (secondi)
        return conn

    def connect(self):
        """Crea una connessione al database usando le credenziali crittografate"""
        existing_conn = self._get_thread_connection()
        if self._is_connection_alive(existing_conn):
            return existing_conn

        # Evita riconnessioni concorrenti nello stesso processo.
        with self._connect_lock:
            existing_conn = self._get_thread_connection()
            if self._is_connection_alive(existing_conn):
                return existing_conn

            self._close_connection_safely(existing_conn)
        try:
            new_conn = self._create_new_connection()
            self._set_thread_connection(new_conn)
            print("Connessione stabilita con successo!")
            return new_conn
        except pyodbc.Error as e:
            print(f"Errore durante la connessione: {str(e)}")
            raise

    def disconnect(self):
        """Chiude la connessione al database"""
        try:
            conn = self._get_thread_connection()
            self._close_connection_safely(conn)
            self._set_thread_connection(None)
        except Exception as e:
            print(f"Errore durante la chiusura della connessione: {str(e)}")

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

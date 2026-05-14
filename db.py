import psycopg2
from psycopg2.extras import RealDictCursor

def get_connection():
    return psycopg2.connect(
        host="localhost",
        database="postgres",
        user="postgres",
        password="Janosia"
    )

def query(sql, params=(), fetchone=False):
    """
    All queries go through here.
    Uses parameterized queries — prevents SQL injection.
    """
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, params)
    conn.commit()
    if fetchone:
        result = cur.fetchone()
    else:
        if cur.description is not None:
            result = cur.fetchall()
        else:
            result = None
    cur.close()
    conn.close()
    return result
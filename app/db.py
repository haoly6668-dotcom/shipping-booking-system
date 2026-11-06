"""Short lived ODBC connections; all business writes go through SQL procedures."""
import re
from contextlib import contextmanager
from flask import current_app
import pyodbc


class BusinessError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.message, self.status = message, status


def translate_error(exc):
    raw = str(exc)
    if '(500' in raw or '(501' in raw or '(510' in raw:
        message = re.sub(r'^.*?\[SQL Server\]', '', raw)
        message = re.sub(r'\s*\(\d+\).*$', '', message).strip(" '[]\")")
        if not message or len(message) > 350:
            message = '操作不符合业务规则，请刷新后检查状态与输入。'
        status = 403 if any(x in message for x in ['权限', '无权', '本人', '自审', '停用', '未授权']) else 409
        return BusinessError(message, status)
    if any(x in raw for x in ['(2627)', '(2601)']):
        return BusinessError('编号、用户名或明细重复，请使用唯一值。')
    if '(547)' in raw:
        return BusinessError('数据不满足约束，或该记录已被业务引用，不能删除。')
    if any(x in raw for x in ['(515)', '(8115)', '(2628)', '(8152)', '22018', '22007']):
        return BusinessError('字段缺失、格式不正确或超出允许范围，请检查输入。', 400)
    if '(1205)' in raw or 'HYT00' in raw:
        return BusinessError('另一个操作正在更新数据，请刷新后重试。')
    current_app.logger.error('Database operation failed: %s', raw)
    return BusinessError('数据库操作暂时不可用，请稍后重试或联系管理员。', 503)


def normalise(row):
    result = {key: ('0x'+bytes(value).hex().upper() if isinstance(value, (bytes, bytearray)) else value)
              for key, value in row.items()}
    # The view names are database terminology; templates use explicit display names.
    aliases = {'origin_name':'origin_port_name','destination_name':'destination_port_name',
               'creator_name':'created_by_name','total_boxes':'total_quantity'}
    for source, target in aliases.items():
        if source in result and target not in result:
            result[target] = result[source]
    return result


@contextmanager
def connection():
    conn = None
    try:
        conn = pyodbc.connect(current_app.config['DB_CONNECTION_STRING'], autocommit=True, timeout=8)
        conn.timeout = 20
        yield conn
    except pyodbc.Error as exc:
        raise translate_error(exc) from exc
    finally:
        if conn is not None:
            conn.close()


class Repository:
    def query(self, sql, params=()):
        with connection() as conn:
            cursor = conn.cursor().execute(sql, tuple(params))
            if not cursor.description:
                return []
            names = [item[0] for item in cursor.description]
            return [normalise(dict(zip(names, row))) for row in cursor.fetchall()]

    def one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql, params=(), default=0):
        row = self.one(sql, params)
        return next(iter(row.values())) if row else default

    def procedure(self, name, **params):
        # Callers use fixed internal procedure names and named parameters only.
        if not re.fullmatch(r'usp_[A-Za-z0-9_]+', name):
            raise ValueError('Invalid internal procedure name')
        for key in params:
            if not re.fullmatch(r'[a-z_]+', key):
                raise ValueError('Invalid internal parameter name')
        sql = 'EXEC dbo.'+name+' '+', '.join('@'+key+'=?' for key in params)
        with connection() as conn:
            cursor = conn.cursor().execute(sql, tuple(params.values()))
            result = []
            while True:
                if cursor.description:
                    names = [item[0] for item in cursor.description]
                    result = [normalise(dict(zip(names, row))) for row in cursor.fetchall()]
                if not cursor.nextset():
                    break
            return result


repo = Repository()

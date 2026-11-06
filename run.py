"""Local WSGI entrypoint. No debug server or network-wide listening by default."""
import os
from waitress import serve
from app import create_app

if __name__=='__main__':
    app=create_app()
    port=int(os.getenv('PORT','5000'))
    print(f'海运订舱系统已启动：http://127.0.0.1:{port}',flush=True)
    serve(app,host='127.0.0.1',port=port,threads=8)

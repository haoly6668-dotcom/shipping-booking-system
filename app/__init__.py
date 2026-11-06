import logging
import os
import secrets
from datetime import timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from flask import Flask
from dotenv import load_dotenv


def create_app(test_config=None):
    root=Path(__file__).resolve().parent.parent
    load_dotenv(root/'.env')
    app=Flask(__name__)
    app.config.update(SECRET_KEY=os.getenv('SECRET_KEY'),DB_CONNECTION_STRING=os.getenv('DB_CONNECTION_STRING'),
        SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=os.getenv('HTTPS_ONLY')=='1',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),MAX_CONTENT_LENGTH=256*1024,TESTING=False)
    if test_config:app.config.update(test_config)
    if not app.config['SECRET_KEY'] or not app.config['DB_CONNECTION_STRING']:
        raise RuntimeError('缺少配置。请先运行 setup.ps1 初始化专用数据库及 .env。')
    logdir=root/'logs';logdir.mkdir(exist_ok=True)
    handler=RotatingFileHandler(logdir/'app.log',maxBytes=1_000_000,backupCount=3,encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    app.logger.addHandler(handler)
    from .routes import bp, install_helpers
    app.register_blueprint(bp);install_helpers(app)
    return app

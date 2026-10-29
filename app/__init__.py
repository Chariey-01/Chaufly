from flask import Flask

from .config import Config
from .extensions import db
from .routes import api, web


def create_app(config_override=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_override:
        app.config.update(config_override)

    db.init_app(app)
    app.register_blueprint(web)
    app.register_blueprint(api, url_prefix="/api")

    with app.app_context():
        db.create_all()

    return app

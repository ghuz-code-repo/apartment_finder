from app import create_app
from app.core.extensions import db
from app.models.news_models import News, NewsMedia

app = create_app()
with app.app_context():
    db.create_all()
    print("Таблицы новостей созданы.")
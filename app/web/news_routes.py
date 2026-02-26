from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app.services import news_service
from app.models.news_models import News
from app.core.decorators import permission_required

news_bp = Blueprint('news', __name__)

@news_bp.route('/market/news')
@login_required
def feed():
    # Загрузка новостей от новых к старым
    news_items = News.query.order_by(News.created_at.desc()).all()
    return render_template('news/feed.html', news_items=news_items)

@news_bp.route('/market/news/add', methods=['POST'])
@login_required
@permission_required('upload_data')
def add_news():
    title = request.form.get('title')
    description = request.form.get('description')
    files = request.files.getlist('files')
    if title and description:
        news_service.save_news(title, description, files)
        flash('Новость опубликована', 'success')
    return redirect(url_for('news.feed'))

@news_bp.route('/market/news/delete/<int:news_id>')
@login_required
@permission_required('upload_data')
def delete_news(news_id):
    news_service.delete_news(news_id)
    flash('Новость удалена', 'info')
    return redirect(url_for('news.feed'))
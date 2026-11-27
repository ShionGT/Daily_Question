import os
import uuid
import json
import hashlib
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, send_from_directory
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import azure.core.exceptions
from azure.data.tables import TableServiceClient, TableClient, UpdateMode
from azure.storage.blob import BlobServiceClient, ContentSettings, generate_blob_sas, BlobSasPermissions
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max upload

# Azure Storage Configuration
STORAGE_CONNECTION_STRING = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
TABLE_STORAGE_CONNECTION_STRING = os.environ.get('AZURE_TABLE_STORAGE_CONNECTION_STRING', STORAGE_CONNECTION_STRING)
BLOB_CONTAINER_NAME = os.environ.get('BLOB_CONTAINER_NAME', 'posts-images')

# Table names
POSTS_TABLE = 'Posts'
COMMENTS_TABLE = 'Comments'
LIKES_TABLE = 'Likes'
DAILY_QUESTIONS_TABLE = 'DailyQuestions'
REPORTS_TABLE = 'Reports'
RATE_LIMIT_TABLE = 'RateLimits'

# Categories
CATEGORIES = [
    '勉強・学習',
    '学校生活',
    '進路・受験',
    '部活動',
    '趣味・雑談',
    'その他'
]

# Daily Questions (pre-defined list)
DAILY_QUESTIONS = [
    "もし明日から学校の授業を1つ自由に追加できるなら、何を追加したい？",
    "これまでで一番印象に残っている学校行事は何？",
    "放課後の過ごし方で、一番多いのはどれ？",
    "苦手な科目を克服するためにやっていることは？",
    "進路決定で一番参考になった情報源は？",
    "部活動・委員会で得た一番のスキルは？",
    "学校のルールで「これ変えたい」と思うものは？",
    "友達との関係で悩んだ時、どう解決してる？",
    "テスト勉強で効果があった方法を教えて！",
    "バイトやインターンで学んだことは？",
    "スマホの使用時間、1日平均どれくらい？",
    "将来の夢・なりたい職業は？",
    "学校の給食・弁当で好きなメニューは？",
    "文化祭・体育祭の思い出エピソードは？",
    "朝起きるのが辛い時の対策は？",
    "図書館・自習室のおすすめの使い方は？",
    "先生に言われて嬉しかった言葉は？",
    "修学旅行・校外学習の思い出は？",
    "受験勉強のモチベ維持方法は？",
    "学校で「これ便利」と思う設備・システムは？",
    "休日のリフレッシュ方法を教えて！",
    "後輩に伝えたい「高校生活のコツ」は？",
    "オンライン授業のメリット・デメリットは？",
    "部活の顧問の先生とのエピソードは？",
    "友達へのプレゼント、予算と選び方は？",
    "学校のトイレ・更衣室の改善点は？",
    "自分の強み・アピールポイントは？",
    "勉強の息抜きに見てる動画・サイトは？",
    "学校のWi-Fi環境、どう思う？",
    "卒業までにやっておきたいことは？"
]

# Initialize Azure clients
def get_table_service():
    if not TABLE_STORAGE_CONNECTION_STRING:
        return None
    try:
        return TableServiceClient.from_connection_string(TABLE_STORAGE_CONNECTION_STRING)
    except Exception:
        return None

def get_blob_service():
    if not STORAGE_CONNECTION_STRING:
        return None
    try:
        return BlobServiceClient.from_connection_string(STORAGE_CONNECTION_STRING)
    except Exception:
        return None

def init_tables():
    """Create tables if they don't exist"""
    table_service = get_table_service()
    if not table_service:
        return
    
    for table_name in [POSTS_TABLE, COMMENTS_TABLE, LIKES_TABLE, DAILY_QUESTIONS_TABLE, REPORTS_TABLE, RATE_LIMIT_TABLE]:
        try:
            table_service.create_table_if_not_exists(table_name)
        except Exception as e:
            print(f"Table creation warning for {table_name}: {e}")

def get_table_client(table_name):
    table_service = get_table_service()
    if not table_service:
        return None
    return table_service.get_table_client(table_name)

def get_jst_now():
    """Get current time in JST (UTC+9)"""
    return datetime.now(timezone(timedelta(hours=9)))

def get_today_question():
    """Get today's question based on date"""
    jst_now = get_jst_now()
    day_of_year = jst_now.timetuple().tm_yday - 1  # 0-indexed
    question_index = day_of_year % len(DAILY_QUESTIONS)
    return DAILY_QUESTIONS[question_index], jst_now.strftime('%Y-%m-%d')

def get_client_identifier():
    """Get identifier for rate limiting (IP + User-Agent hash)"""
    ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    ua = request.environ.get('HTTP_USER_AGENT', '')
    combined = f"{ip}:{ua}"
    return hashlib.sha256(combined.encode()).hexdigest()[:16]

def check_rate_limit(action, limit_seconds=30):
    """Check and update rate limit for an action"""
    identifier = get_client_identifier()
    table_client = get_table_client(RATE_LIMIT_TABLE)
    if not table_client:
        return True  # Allow if no table storage
    
    try:
        entity = table_client.get_entity(partition_key=action, row_key=identifier)
        last_time = datetime.fromisoformat(entity['LastAction'].replace('Z', '+00:00'))
        if (get_jst_now().replace(tzinfo=None) - last_time.replace(tzinfo=None)).total_seconds() < limit_seconds:
            return False
    except azure.core.exceptions.ResourceNotFoundError:
        pass  # First time, allow
    
    # Update or create rate limit entry
    entity = {
        'PartitionKey': action,
        'RowKey': identifier,
        'LastAction': get_jst_now().isoformat()
    }
    try:
        table_client.upsert_entity(entity, mode=UpdateMode.MERGE)
    except Exception:
        pass
    return True

import html

def sanitize_input(text):
    """Basic XSS prevention - escape HTML"""
    if not text:
        return ''
    return html.escape(text)

def validate_image(file):
    """Validate uploaded image"""
    if not file or not file.filename:
        return False, "ファイルが選択されていません"
    
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    
    if ext not in allowed_extensions:
        return False, "対応していないファイル形式です (PNG, JPG, GIF, WebPのみ)"
    
    # Check MIME type
    allowed_mimes = {'image/png', 'image/jpeg', 'image/gif', 'image/webp'}
    if file.mimetype not in allowed_mimes:
        return False, "不正なファイルタイプです"
    
    # Check file size (5MB)
    file.seek(0, 2)  # Seek to end
    size = file.tell()
    file.seek(0)  # Reset
    if size > 5 * 1024 * 1024:
        return False, "ファイルサイズは5MB以下にしてください"
    
    return True, filename

def upload_image_to_blob(file, filename):
    """Upload image to Azure Blob Storage"""
    blob_service = get_blob_service()
    if not blob_service:
        return None
    
    try:
        container_client = blob_service.get_container_client(BLOB_CONTAINER_NAME)
        # Create container if not exists
        try:
            container_client.create_container()
        except Exception:
            pass  # Already exists
        
        # Generate unique blob name
        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'png'
        blob_name = f"{uuid.uuid4().hex}.{ext}"
        
        blob_client = container_client.get_blob_client(blob_name)
        content_settings = ContentSettings(content_type=file.mimetype)
        blob_client.upload_blob(file, overwrite=True, content_settings=content_settings)
        
        # Generate SAS URL (valid for 1 year)
        sas_token = generate_blob_sas(
            account_name=blob_service.account_name,
            container_name=BLOB_CONTAINER_NAME,
            blob_name=blob_name,
            account_key=blob_service.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(days=365)
        )
        return f"https://{blob_service.account_name}.blob.core.windows.net/{BLOB_CONTAINER_NAME}/{blob_name}?{sas_token}"
    except Exception as e:
        print(f"Blob upload error: {e}")
        return None

# Initialize tables on startup
with app.app_context():
    init_tables()

# ===== ROUTES =====

@app.route('/')
def index():
    """Top page - Today's question + categories + latest posts"""
    question_text, question_date = get_today_question()
    
    # Get latest posts (5)
    posts_table = get_table_client(POSTS_TABLE)
    latest_posts = []
    if posts_table:
        try:
            entities = posts_table.query_entities(
                query_filter="",
                results_per_page=5
            )
            for entity in entities.by_page().next():
                latest_posts.append({
                    'id': entity['RowKey'],
                    'category': entity['PartitionKey'],
                    'title': entity['Title'],
                    'content': entity['Content'][:100] + '...' if len(entity['Content']) > 100 else entity['Content'],
                    'created_at': entity['CreatedAt'],
                    'like_count': entity.get('LikeCount', 0),
                    'image_url': entity.get('ImageUrl', '')
                })
        except Exception as e:
            print(f"Error fetching latest posts: {e}")
    
    return render_template('index.html', 
                         question_text=question_text,
                         question_date=question_date,
                         categories=CATEGORIES,
                         latest_posts=latest_posts)

@app.route('/board')
def board():
    """Board list with category filter"""
    category = request.args.get('category', '')
    page = int(request.args.get('page', 1))
    per_page = 10
    
    posts_table = get_table_client(POSTS_TABLE)
    posts = []
    total = 0
    
    if posts_table:
        try:
            if category and category in CATEGORIES:
                query = f"PartitionKey eq '{category}'"
            else:
                query = ""
            
            # Get all for count (simple approach)
            all_entities = list(posts_table.query_entities(query_filter=query))
            total = len(all_entities)
            
            # Sort by CreatedAt descending
            all_entities.sort(key=lambda x: x['CreatedAt'], reverse=True)
            
            # Paginate
            start = (page - 1) * per_page
            end = start + per_page
            page_entities = all_entities[start:end]
            
            for entity in page_entities:
                posts.append({
                    'id': entity['RowKey'],
                    'category': entity['PartitionKey'],
                    'title': entity['Title'],
                    'content': entity['Content'][:150] + '...' if len(entity['Content']) > 150 else entity['Content'],
                    'created_at': entity['CreatedAt'],
                    'like_count': entity.get('LikeCount', 0),
                    'image_url': entity.get('ImageUrl', '')
                })
        except Exception as e:
            print(f"Error fetching posts: {e}")
    
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('board.html',
                         posts=posts,
                         categories=CATEGORIES,
                         current_category=category,
                         page=page,
                         total_pages=total_pages,
                         total=total)

@app.route('/post/<post_id>')
def post_detail(post_id):
    """Post detail with comments"""
    posts_table = get_table_client(POSTS_TABLE)
    comments_table = get_table_client(COMMENTS_TABLE)
    likes_table = get_table_client(LIKES_TABLE)
    
    post = None
    comments = []
    user_liked = False
    
    if posts_table:
        try:
            # Query all partitions for the post ID
            entities = list(posts_table.query_entities(query_filter=f"RowKey eq '{post_id}'"))
            if entities:
                entity = entities[0]
                post = {
                    'id': entity['RowKey'],
                    'category': entity['PartitionKey'],
                    'title': entity['Title'],
                    'content': entity['Content'],
                    'created_at': entity['CreatedAt'],
                    'like_count': entity.get('LikeCount', 0),
                    'image_url': entity.get('ImageUrl', '')
                }
                
                # Check if user liked (using session)
                session_likes = session.get('liked_posts', [])
                user_liked = post_id in session_likes
        except Exception as e:
            print(f"Error fetching post: {e}")
    
    if not post:
        flash('投稿が見つかりません', 'error')
        return redirect(url_for('board'))
    
    # Get comments
    if comments_table:
        try:
            entities = comments_table.query_entities(query_filter=f"PartitionKey eq '{post_id}'")
            for entity in entities:
                comments.append({
                    'id': entity['RowKey'],
                    'content': entity['Content'],
                    'created_at': entity['CreatedAt'],
                    'nickname': entity.get('Nickname', '匿名')
                })
            # Sort by created_at
            comments.sort(key=lambda x: x['created_at'])
        except Exception as e:
            print(f"Error fetching comments: {e}")
    
    return render_template('post_detail.html',
                         post=post,
                         comments=comments,
                         user_liked=user_liked)

@app.route('/create', methods=['GET', 'POST'])
def create_post():
    """Create new post"""
    if request.method == 'GET':
        return render_template('create.html', categories=CATEGORIES)
    
    # Rate limit check
    if not check_rate_limit('create_post', 30):
        flash('投稿間隔を空けてください（30秒以上）', 'error')
        return redirect(url_for('create_post'))
    
    title = sanitize_input(request.form.get('title', '').strip())
    content = sanitize_input(request.form.get('content', '').strip())
    category = request.form.get('category', '')
    nickname = sanitize_input(request.form.get('nickname', '').strip()) or '匿名'
    image_file = request.files.get('image')
    
    # Validation
    errors = []
    if not title:
        errors.append('タイトルを入力してください')
    if len(title) > 100:
        errors.append('タイトルは100文字以内で入力してください')
    if not content:
        errors.append('本文を入力してください')
    if len(content) > 5000:
        errors.append('本文は5000文字以内で入力してください')
    if category not in CATEGORIES:
        errors.append('カテゴリーを選択してください')
    
    if errors:
        for err in errors:
            flash(err, 'error')
        return render_template('create.html', categories=CATEGORIES,
                             title=title, content=content, category=category, nickname=nickname)
    
    # Handle image upload
    image_url = ''
    if image_file and image_file.filename:
        valid, result = validate_image(image_file)
        if not valid:
            flash(result, 'error')
            return render_template('create.html', categories=CATEGORIES,
                                 title=title, content=content, category=category, nickname=nickname)
        image_url = upload_image_to_blob(image_file, result) or ''
    
    # Save to Table Storage
    posts_table = get_table_client(POSTS_TABLE)
    if posts_table:
        try:
            post_id = uuid.uuid4().hex
            entity = {
                'PartitionKey': category,
                'RowKey': post_id,
                'Title': title,
                'Content': content,
                'CreatedAt': get_jst_now().isoformat(),
                'ImageUrl': image_url,
                'LikeCount': 0,
                'Nickname': nickname
            }
            posts_table.create_entity(entity)
            flash('投稿しました！', 'success')
            return redirect(url_for('post_detail', post_id=post_id))
        except Exception as e:
            print(f"Error creating post: {e}")
            flash('投稿に失敗しました。もう一度お試しください。', 'error')
    else:
        flash('データベース接続エラー', 'error')
    
    return render_template('create.html', categories=CATEGORIES,
                         title=title, content=content, category=category, nickname=nickname)

@app.route('/post/<post_id>/comment', methods=['POST'])
def add_comment(post_id):
    """Add comment to post"""
    if not check_rate_limit('add_comment', 10):
        return jsonify({'success': False, 'error': 'コメント間隔を空けてください（10秒以上）'}), 429
    
    content = sanitize_input(request.form.get('content', '').strip())
    nickname = sanitize_input(request.form.get('nickname', '').strip()) or '匿名'
    
    if not content:
        return jsonify({'success': False, 'error': 'コメントを入力してください'}), 400
    if len(content) > 2000:
        return jsonify({'success': False, 'error': 'コメントは2000文字以内で入力してください'}), 400
    
    comments_table = get_table_client(COMMENTS_TABLE)
    if comments_table:
        try:
            comment_id = uuid.uuid4().hex
            entity = {
                'PartitionKey': post_id,
                'RowKey': comment_id,
                'Content': content,
                'CreatedAt': get_jst_now().isoformat(),
                'Nickname': nickname
            }
            comments_table.create_entity(entity)
            return jsonify({'success': True})
        except Exception as e:
            print(f"Error adding comment: {e}")
            return jsonify({'success': False, 'error': 'コメントの投稿に失敗しました'}), 500
    
    return jsonify({'success': False, 'error': 'データベース接続エラー'}), 500

@app.route('/post/<post_id>/like', methods=['POST'])
def toggle_like(post_id):
    """Toggle like on post"""
    session_likes = session.get('liked_posts', [])
    
    posts_table = get_table_client(POSTS_TABLE)
    if not posts_table:
        return jsonify({'success': False, 'error': 'データベース接続エラー'}), 500
    
    try:
        entities = list(posts_table.query_entities(query_filter=f"RowKey eq '{post_id}'"))
        if not entities:
            return jsonify({'success': False, 'error': '投稿が見つかりません'}), 404
        
        entity = entities[0]
        current_likes = entity.get('LikeCount', 0)
        
        if post_id in session_likes:
            # Unlike
            current_likes = max(0, current_likes - 1)
            session_likes.remove(post_id)
            liked = False
        else:
            # Like
            current_likes += 1
            session_likes.append(post_id)
            liked = True
        
        entity['LikeCount'] = current_likes
        posts_table.update_entity(entity, mode=UpdateMode.MERGE)
        session['liked_posts'] = session_likes
        
        return jsonify({'success': True, 'like_count': current_likes, 'liked': liked})
    except Exception as e:
        print(f"Error toggling like: {e}")
        return jsonify({'success': False, 'error': 'いいねの処理に失敗しました'}), 500

@app.route('/post/<post_id>/report', methods=['POST'])
def report_post(post_id):
    """Report a post"""
    if not check_rate_limit('report_post', 60):
        return jsonify({'success': False, 'error': '通報間隔を空けてください（60秒以上）'}), 429
    
    reason = sanitize_input(request.form.get('reason', '').strip())
    detail = sanitize_input(request.form.get('detail', '').strip())
    
    if not reason:
        return jsonify({'success': False, 'error': '通報理由を選択してください'}), 400
    
    reports_table = get_table_client(REPORTS_TABLE)
    if reports_table:
        try:
            report_id = uuid.uuid4().hex
            entity = {
                'PartitionKey': post_id,
                'RowKey': report_id,
                'Reason': reason,
                'Detail': detail,
                'CreatedAt': get_jst_now().isoformat()
            }
            reports_table.create_entity(entity)
            return jsonify({'success': True})
        except Exception as e:
            print(f"Error reporting post: {e}")
            return jsonify({'success': False, 'error': '通報に失敗しました'}), 500
    
    return jsonify({'success': False, 'error': 'データベース接続エラー'}), 500

@app.route('/question')
def question_page():
    """Today's question page"""
    question_text, question_date = get_today_question()
    
    # Get answers for today's question (stored as posts with special category)
    posts_table = get_table_client(POSTS_TABLE)
    answers = []
    if posts_table:
        try:
            entities = list(posts_table.query_entities(query_filter="PartitionKey eq '今日の質問'"))
            entities.sort(key=lambda x: x['CreatedAt'], reverse=True)
            for entity in entities[:20]:
                answers.append({
                    'id': entity['RowKey'],
                    'content': entity['Content'],
                    'created_at': entity['CreatedAt'],
                    'nickname': entity.get('Nickname', '匿名')
                })
        except Exception as e:
            print(f"Error fetching answers: {e}")
    
    # Past questions
    jst_now = get_jst_now()
    past_questions = []
    for i in range(1, 8):  # Last 7 days
        past_date = jst_now - timedelta(days=i)
        day_of_year = past_date.timetuple().tm_yday - 1
        q_index = day_of_year % len(DAILY_QUESTIONS)
        past_questions.append({
            'date': past_date.strftime('%Y-%m-%d'),
            'question': DAILY_QUESTIONS[q_index]
        })
    
    return render_template('question.html',
                         question_text=question_text,
                         question_date=question_date,
                         answers=answers,
                         past_questions=past_questions)

@app.route('/question/answer', methods=['POST'])
def answer_question():
    """Answer today's question"""
    if not check_rate_limit('answer_question', 30):
        flash('回答間隔を空けてください（30秒以上）', 'error')
        return redirect(url_for('question_page'))
    
    content = sanitize_input(request.form.get('content', '').strip())
    nickname = sanitize_input(request.form.get('nickname', '').strip()) or '匿名'
    
    if not content:
        flash('回答を入力してください', 'error')
        return redirect(url_for('question_page'))
    if len(content) > 2000:
        flash('回答は2000文字以内で入力してください', 'error')
        return redirect(url_for('question_page'))
    
    posts_table = get_table_client(POSTS_TABLE)
    if posts_table:
        try:
            question_text, question_date = get_today_question()
            post_id = uuid.uuid4().hex
            entity = {
                'PartitionKey': '今日の質問',
                'RowKey': post_id,
                'Title': f'今日の質問: {question_text[:30]}...',
                'Content': content,
                'CreatedAt': get_jst_now().isoformat(),
                'ImageUrl': '',
                'LikeCount': 0,
                'Nickname': nickname,
                'QuestionDate': question_date,
                'QuestionText': question_text
            }
            posts_table.create_entity(entity)
            flash('回答しました！', 'success')
        except Exception as e:
            print(f"Error answering question: {e}")
            flash('回答に失敗しました', 'error')
    else:
        flash('データベース接続エラー', 'error')
    
    return redirect(url_for('question_page'))

@app.route('/admin/reports')
def admin_reports():
    """Admin panel to view reports (simple implementation)"""
    # Simple auth - in production, use proper authentication
    auth_key = request.args.get('key', '')
    if auth_key != os.environ.get('ADMIN_KEY', 'admin-secret-change-me'):
        return 'Unauthorized', 401
    
    reports_table = get_table_client(REPORTS_TABLE)
    posts_table = get_table_client(POSTS_TABLE)
    
    reports = []
    if reports_table:
        try:
            entities = list(reports_table.query_entities(query_filter=""))
            entities.sort(key=lambda x: x['CreatedAt'], reverse=True)
            
            for entity in entities:
                post_id = entity['PartitionKey']
                post_info = {'title': '不明', 'content': ''}
                if posts_table:
                    try:
                        post_entities = list(posts_table.query_entities(query_filter=f"RowKey eq '{post_id}'"))
                        if post_entities:
                            post_info = {
                                'title': post_entities[0]['Title'],
                                'content': post_entities[0]['Content'][:100]
                            }
                    except Exception:
                        pass
                
                reports.append({
                    'id': entity['RowKey'],
                    'post_id': post_id,
                    'post_title': post_info['title'],
                    'post_content': post_info['content'],
                    'reason': entity['Reason'],
                    'detail': entity.get('Detail', ''),
                    'created_at': entity['CreatedAt']
                })
        except Exception as e:
            print(f"Error fetching reports: {e}")
    
    return render_template('admin_reports.html', reports=reports)

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'timestamp': get_jst_now().isoformat()})

# Static files
@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

# Error handlers
@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', 'False').lower() == 'true')
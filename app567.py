import matplotlib
matplotlib.use('Agg')  # 非インタラクティブバックエンドを設定

import io
import os  # 環境変数の読み込みに使用
from datetime import datetime, timedelta  # timedeltaを追加
import pandas as pd
import matplotlib.pyplot as plt
from flask import Flask, render_template, request, send_file, redirect, url_for, jsonify, session, flash
import base64
from matplotlib import font_manager
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import FlaskForm  # Flask-WTFのインポート
from wtforms import StringField, PasswordField, SubmitField, FloatField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError, NumberRange
from flask import flash, redirect, url_for

app = Flask(__name__)

# セッション管理のためのシークレットキーを設定（安全なランダムな文字列に変更してください）
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your_default_secret_key_here')  # ⚠️ 本番環境では環境変数から取得

# セッションの有効期限を10分に設定
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)

# Database configuration with absolute path
basedir = os.path.abspath(os.path.dirname(__file__))
database_path = os.path.join(basedir, 'expenses567.db')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + database_path
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Flask-Loginの設定
login_manager = LoginManager(app)
login_manager.login_view = 'login'  # ログインが必要な場合にリダイレクトするビュー
login_manager.login_message_category = 'info'

# Flask-Migrateの初期化（モデル定義後に移動）
migrate = Migrate(app, db)

# Font setup for Japanese rendering in graphs
font_path = 'C:/Windows/Fonts/msgothic.ttc'  # 適切なフォントパスに変更してください
font_prop = font_manager.FontProperties(fname=font_path)
plt.rcParams['font.family'] = font_prop.get_name()

# Expense model
class Expense(db.Model):
    __tablename__ = 'expense'  # テーブル名を明示的に指定
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    date = db.Column(db.String(10), nullable=False)  # Format: YYYY-MM-DD
    amount = db.Column(db.Float, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # 初期はnullable=True

    user = db.relationship('User', backref=db.backref('expenses', lazy=True))  # 関係の定義

    def __repr__(self):
        return f"<Expense {self.year}-{self.month}-{self.date}: {self.amount}万円>"

# User model
class User(db.Model, UserMixin):  # UserMixinを継承
    __tablename__ = 'user'  # テーブル名を明示的に指定
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.username}>"

# SimulationResultモデルの追加
class SimulationResult(db.Model):
    __tablename__ = 'simulation_result'  # テーブル名を明示的に指定
    id = db.Column(db.Integer, primary_key=True)
    ideal_living_expense = db.Column(db.Float, nullable=True)
    graph_url = db.Column(db.String(500), nullable=True)
    monthly_targets = db.Column(db.PickleType, nullable=True)  # リストを保存するためにPickleTypeを使用
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    user = db.relationship('User', backref=db.backref('simulation_results', lazy=True))

    def __repr__(self):
        return f"<SimulationResult User:{self.user.username} Ideal:{self.ideal_living_expense}>"

# ユーザーのロード関数（Flask-Login用）
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# Flask-WTFフォームの定義
class RegistrationForm(FlaskForm):
    username = StringField('ユーザー名', validators=[DataRequired(), Length(min=2, max=150)])
    password = PasswordField('パスワード', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('パスワード確認', validators=[DataRequired(), EqualTo('password', message='パスワードが一致しません。')])
    submit = SubmitField('登録')

    # ユーザー名の重複チェック
    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('このユーザー名は既に使用されています。別の名前を選んでください。')

class LoginForm(FlaskForm):
    username = StringField('ユーザー名', validators=[DataRequired(), Length(min=2, max=150)])
    password = PasswordField('パスワード', validators=[DataRequired()])
    submit = SubmitField('ログイン')

class MonthlyGoalForm(FlaskForm):
    annual_goal = FloatField(
        '年間目標 (万円)',
        validators=[
            DataRequired(message="年間目標を入力してください。"),
            NumberRange(min=0, message="正の数を入力してください。")
        ]
    )
    submit = SubmitField('目標を設定')

# Function to calculate ideal living expenses and asset transition
def calculate_living_expenses(current_age, retirement_age, current_income, current_savings,
                              peak_income, rent, car_start_age, car_price, car_interval):
    person_ages = list(range(current_age, 91))
    income = [
        round(current_income + (peak_income - current_income) / (retirement_age - current_age) * (age - current_age))
        if current_age <= age <= retirement_age else 0 for age in person_ages
    ]
    average_income = (current_income + peak_income) / 2
    pension_amount = 80 + 0.22 * average_income * (retirement_age - 23) / 40
    for i in range(len(person_ages)):
        if person_ages[i] >= 65:
            income[i] = round(pension_amount)

    living_expenses = [216] * len(person_ages)
    housing_expenses = [rent] * len(person_ages)
    car_expenses = [
        car_price if (car_start_age and age >= car_start_age and (age - car_start_age) % car_interval == 0 and age <= 75) else 0
        for age in person_ages
    ]

    net_savings = [round(income[i] - (living_expenses[i] + housing_expenses[i] + car_expenses[i]))
                   for i in range(len(person_ages))]
    assets = [current_savings]
    for i in range(1, len(net_savings)):
        assets.append(assets[-1] + net_savings[i])

    for _ in range(1000):
        if assets[-1] > 0:
            living_expenses = [x + 1 for x in living_expenses]
        elif assets[-1] < 0:
            living_expenses = [x - 1 for x in living_expenses]
        else:
            break
        net_savings = [round(income[i] - (living_expenses[i] + housing_expenses[i] + car_expenses[i]))
                       for i in range(len(person_ages))]
        assets = [current_savings]
        for i in range(1, len(net_savings)):
            assets.append(assets[-1] + net_savings[i])

    return living_expenses[0], person_ages, assets, income, living_expenses, car_expenses

# Home page route
@app.route('/')
@login_required  # ログインが必要
def index():
    # シミュレーション結果をデータベースから取得
    simulation = SimulationResult.query.filter_by(user_id=current_user.id).first()
    ideal_living_expense = simulation.ideal_living_expense if simulation else "未設定"
    comments = "今年も残り1か月！ふるさと納税はもうやったかな？"

    # Retrieve the selected starting month and year from query parameters
    start_month = request.args.get('start_month', default=12, type=int)  # Default to December
    start_year = request.args.get('start_year', default=datetime.now().year, type=int)  # Default to current year

    # バリデーション
    if start_month < 1 or start_month > 12:
        start_month = 12  # バリデーション
    if start_year < 2000 or start_year > 2100:
        start_year = datetime.now().year  # バリデーション

    # Define month names
    months = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"]

    # Define a range of years (e.g., current year -5 to current year +5)
    current_year_value = datetime.now().year
    years = list(range(current_year_value - 5, current_year_value + 6))

    # Rearrange months based on start_month
    start_index = start_month - 1
    reordered_months = months[start_index:] + months[:start_index]

    # Retrieve monthly_targets from simulation_result
    monthly_targets = simulation.monthly_targets if simulation else [0] * 12

    # Rearrange monthly_targets based on start_month
    reordered_monthly_targets = monthly_targets[start_index:] + monthly_targets[:start_index]

    # Collect actual expenses for each month over 12 months starting from start_year and start_month
    monthly_actuals = []
    for i in range(12):
        # Calculate the correct year and month
        month_number = (start_month + i - 1) % 12 + 1
        year_increment = (start_month + i - 1) // 12
        year = start_year + year_increment
        month_padded = str(month_number).zfill(2)
        month_key = f"{year}-{month_padded}"
        # Fetch expenses from the database for the current user
        expenses = Expense.query.filter_by(year=year, month=month_number, user_id=current_user.id).all()
        total_expenses = sum(exp.amount for exp in expenses)
        monthly_actuals.append(total_expenses)

    # Rearrange monthly_actuals based on start_month
    reordered_monthly_actuals = monthly_actuals

    # Generate bar chart
    img = io.BytesIO()
    plt.figure(figsize=(10, 5))
    bar_width = 0.4
    index = range(len(reordered_months))

    # 青色部分（目標）
    plt.bar(index, reordered_monthly_targets, bar_width, label="目標", color="blue", alpha=0.6)

    # オレンジ部分（目標内の支出）
    actual_under_target = [min(a, t) for a, t in zip(reordered_monthly_actuals, reordered_monthly_targets)]
    plt.bar(index, actual_under_target, bar_width, label="支出（目標内）", color="orange", alpha=0.8)

    # 赤色部分（目標を超えた支出）
    actual_over_target = [max(0, a - t) for a, t in zip(reordered_monthly_actuals, reordered_monthly_targets)]
    plt.bar(index, actual_over_target, bar_width, bottom=actual_under_target, label="目標超過", color="red", alpha=0.8)

    # グラフのカスタマイズ
    plt.xticks(index, reordered_months)
    plt.xlabel("月")
    plt.ylabel("金額 (万円)")
    plt.title("月ごとの目標と支出")
    plt.legend()
    plt.grid(axis="y", linestyle="--", alpha=0.7)
    plt.tight_layout()
    plt.savefig(img, format="png")
    img.seek(0)
    bar_chart_url = base64.b64encode(img.getvalue()).decode()

    return render_template(
        'index567.html',
        ideal_living_expense=ideal_living_expense,
        comments=comments,
        bar_chart_url=bar_chart_url,
        months=months,
        years=years,
        selected_month=start_month,
        selected_year=start_year
    )

# 収支目標ページ
@app.route('/monthly-goal', methods=['GET', 'POST'])
@login_required
def monthly_goal():
    simulation = SimulationResult.query.filter_by(user_id=current_user.id).first()
    form = MonthlyGoalForm()

    if form.validate_on_submit():
        annual_goal = form.annual_goal.data
        monthly_goal = round(annual_goal / 12, 2)

        if simulation:
            simulation.ideal_living_expense = annual_goal
            simulation.monthly_targets = [monthly_goal] * 12
        else:
            simulation = SimulationResult(
                ideal_living_expense=annual_goal,
                monthly_targets=[monthly_goal] * 12,
                user_id=current_user.id
            )
            db.session.add(simulation)
        db.session.commit()
        flash('収支目標が更新されました。', 'success')
        return redirect(url_for('monthly_goal'))

    elif request.method == 'GET' and simulation:
        form.annual_goal.data = simulation.ideal_living_expense

    annual_goal = simulation.ideal_living_expense if simulation else "未設定"
    monthly_goal = round(annual_goal / 12, 2) if isinstance(annual_goal, (int, float)) else "未設定"

    return render_template(
        'monthly_goal567.html',
        annual_goal=annual_goal,
        monthly_goal=monthly_goal,
        form=form
    )

# 支出情報を保存するルート
@app.route('/save-expenses', methods=['POST'])
@login_required
def save_expenses():
    data = request.json
    year = data.get('year')
    month = data.get('month')
    expenses = data.get('expenses', {})
    if year and month:
        # 既存の支出をユーザーごとに削除
        Expense.query.filter_by(year=year, month=month, user_id=current_user.id).delete()
        # 新しい支出を追加
        for date, amount in expenses.items():
            new_expense = Expense(year=year, month=month, date=date, amount=amount, user_id=current_user.id)
            db.session.add(new_expense)
        db.session.commit()
        print(f"Saved expenses for user {current_user.username} for {year}-{str(month).zfill(2)}: {expenses}")  # デバッグ用
    return jsonify({"status": "success"})

# 支出情報を取得するルート
@app.route('/get-expenses', methods=['GET'])
@login_required
def get_expenses():
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    if not (year and month):
        return jsonify({})
    expenses = Expense.query.filter_by(year=year, month=month, user_id=current_user.id).all()
    expenses_dict = {expense.date: expense.amount for expense in expenses}
    print(f"Fetched expenses for user {current_user.username} for {year}-{str(month).zfill(2)}: {expenses_dict}")  # デバッグ用
    return jsonify(expenses_dict)

# 支出情報を削除するルート
@app.route('/delete-expense', methods=['POST'])
@login_required
def delete_expense():
    data = request.json
    year = data.get('year')
    month = data.get('month')
    date = data.get('date')
    if not (year and month and date):
        return jsonify({"status": "failure", "message": "Invalid parameters."})
    expense = Expense.query.filter_by(year=year, month=month, date=date, user_id=current_user.id).first()
    if expense:
        db.session.delete(expense)
        db.session.commit()
        print(f"Deleted expense for user {current_user.username} for {year}-{str(month).zfill(2)} on {date}")  # デバッグ用
        return jsonify({"status": "success"})
    return jsonify({"status": "failure", "message": "Expense not found."})

# チャットページ
@app.route('/chat')
@login_required
def chat():
    return render_template('chat567.html')

# サブスクリプションページ
@app.route('/subscription')
@login_required
def subscription():
    return render_template('subscription567.html')

# ヒアリングページ
@app.route('/hearing')
@login_required
def hearing():
    return render_template('hearing567.html')

# マイライフプランページ
@app.route('/my-lifeplan')
@login_required
def my_lifeplan():
    simulation = SimulationResult.query.filter_by(user_id=current_user.id).first()
    return render_template(
        'my_lifeplan567.html',
        ideal_living_expense=simulation.ideal_living_expense if simulation else None,
        graph_url=simulation.graph_url if simulation else None
    )

# シミュレーション実行ルート
@app.route('/simulate', methods=['POST'])
@login_required
def simulate():
    try:
        current_age = int(request.form['age'])
        retirement_age = int(request.form['retirement_age'])
        current_income = int(request.form['income'])
        current_savings = int(request.form['savings'])
        peak_income = int(request.form['peak_income'])
        rent = int(request.form['rent'])
        car_start_age = int(request.form['car_start_age']) if request.form['car_start_age'] else None
        car_price = int(request.form['car_price']) if request.form['car_price'] else 0
        car_interval = int(request.form['car_interval']) if request.form['car_interval'] else 0

        ideal_living_expense, person_ages, assets, income, living_expenses, car_expenses = calculate_living_expenses(
            current_age, retirement_age, current_income, current_savings, peak_income, rent, car_start_age, car_price, car_interval
        )

        df = pd.DataFrame({
            '年齢': person_ages,
            '収入 (万円)': income,
            '支出 (万円)': living_expenses,
            '住居費 (万円)': [rent] * len(person_ages),
            '自動車費 (万円)': car_expenses,
            '年間貯蓄 (万円)': [income[i] - (living_expenses[i] + rent + car_expenses[i]) for i in range(len(person_ages))],
            '資産額 (万円)': assets
        })

        output_file_path = os.path.join(basedir, '理想生活費シミュレーション567.xlsx')
        with pd.ExcelWriter(output_file_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Sheet1', index=False)
            worksheet = writer.sheets['Sheet1']
            for col in worksheet.columns:
                col_letter = col[0].column_letter
                if col_letter != 'A':
                    worksheet.column_dimensions[col_letter].width = 15

        img = io.BytesIO()
        plt.figure(figsize=(12, 6))
        plt.plot(person_ages, assets, label="資産額 (万円)", color='b')
        plt.xlabel('年齢')
        plt.ylabel('資産額 (万円)')
        plt.title('理想生活費シミュレーション')
        plt.xticks(range(current_age, 91, 2))
        plt.grid(True)
        plt.legend(loc='upper right')
        plt.savefig(img, format='png')
        img.seek(0)
        graph_url = base64.b64encode(img.getvalue()).decode()

        # 既存のシミュレーション結果を削除（ユーザーごとに1つのみ保持する場合）
        existing_result = SimulationResult.query.filter_by(user_id=current_user.id).first()
        if existing_result:
            db.session.delete(existing_result)
            db.session.commit()

        # 新しいシミュレーション結果を作成
        new_result = SimulationResult(
            ideal_living_expense=ideal_living_expense,
            graph_url=graph_url,
            monthly_targets=[round(ideal_living_expense / 12)] * 12,
            user_id=current_user.id
        )
        db.session.add(new_result)
        db.session.commit()

        return redirect(url_for('my_lifeplan'))

    except Exception as e:
        print(f"Error generating Excel: {e}")
        return f"Error: {e}"

# Excelダウンロードルート
@app.route('/download')
@login_required
def download():
    excel_path = os.path.join(basedir, '理想生活費シミュレーション567.xlsx')
    if os.path.exists(excel_path):
        return send_file(excel_path, as_attachment=True)
    else:
        flash('ファイルが存在しません。シミュレーションを実行してください。', 'warning')
        return redirect(url_for('simulate'))

# **新しいルート: アバウトページ（about567.html）**
@app.route('/about')
@login_required
def about():
    return render_template('about567.html')

# **ユーザー登録ページ**
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegistrationForm()  # フォームのインスタンス化
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        # ユーザー名の重複チェックはフォームで既に行われている
        new_user = User(username=username)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash('アカウントが作成されました。ログインしてください。', 'success')
        return redirect(url_for('login'))
    return render_template('register567.html', form=form)

# **ログインページ**
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()  # フォームのインスタンス化
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user, remember=False)  # Flask-Loginのlogin_userを使用
            session.permanent = True  # セッションを永続的に設定
            flash('ログインに成功しました。', 'success')
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        else:
            flash('無効なユーザー名またはパスワードです。', 'danger')
    return render_template('login567.html', form=form)

# **ログアウトルート**
@app.route('/logout')
@login_required
def logout():
    logout_user()  # Flask-Loginのlogout_userを使用
    flash('ログアウトしました。', 'info')
    return redirect(url_for('index'))

# **マイページ（例）**
@app.route('/mypage')
@login_required
def mypage():
    user = current_user  # Flask-Loginのcurrent_userを使用
    return render_template('mypage567.html', user=user)

# エラーハンドリングの追加
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5567, debug=True)  # debug=Trueでデバッグモードを有効

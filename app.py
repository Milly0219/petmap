from flask import Flask,session,jsonify, request, redirect, render_template
from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
import pandas as pd
import mysql.connector
import os
import requests
from mysql.connector import connect
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import openai
from dotenv import dotenv_values


load_dotenv()

# 現在可以通過 os.getenv() 來訪問這些環境變數
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_HOST = os.getenv('DB_HOST')
DB_NAME = os.getenv('DB_NAME')

API_KEY = os.getenv('API_KEY')
API_URL = os.getenv('API_URL')
openai.api_key = dotenv_values('.env')["API_KEY2"]


# 1. 檢查並建立資料庫
def initialize_database():
    try:
        # 連接到 MySQL 伺服器（不指定資料庫）
        cnx = connect(user=DB_USER, password=DB_PASSWORD, host=DB_HOST)
        cursor = cnx.cursor()

        # 檢查是否存在資料庫
        cursor.execute(f"SHOW DATABASES LIKE '{DB_NAME}'")
        database_exists = cursor.fetchone()

        if not database_exists:
            # 如果資料庫不存在，建立資料庫
            cursor.execute(f"CREATE DATABASE {DB_NAME} DEFAULT CHARACTER SET 'utf8'")
            print(f"資料庫 '{DB_NAME}' 已建立。")
            import_data()
        else:
            print(f"資料庫 '{DB_NAME}' 已存在。")

        cursor.close()
        cnx.close()

    except Exception as e:
        print(f"資料庫初始化錯誤: {e}")

# 2. 定義資料表和匯入資料
def import_data():
    engine = create_engine(f'mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}')
    Base = declarative_base()

    class PetLost(Base):
        __tablename__ = 'pet_lost'
        
        id = Column(Integer, primary_key=True, autoincrement=True)
        chip_number = Column(String(50))
        pet_name = Column(String(50))
        pet_type = Column(String(10))
        gender = Column(String(10))
        breed = Column(String(50))
        color = Column(String(50))
        appearance = Column(String(50))
        features = Column(String(255))
        lost_date = Column(String(50))
        lost_location = Column(String(255))
        latitude = Column(Float)
        longitude = Column(Float)
        owner_name = Column(String(50))
        contact_phone = Column(String(50))
        email = Column(String(100))
        photo_url = Column(String(255))
        ad_content= Column(String(255))

    # 建立表格
    Base.metadata.create_all(engine)

    # 將 Excel 資料匯入 MySQL
    Session = sessionmaker(bind=engine)
    session = Session()

    # 讀取 Excel 檔案並清理資料
    file_path = 'static/tables/pet_lost.xlsx'
    if not os.path.exists(file_path):
        print(f"檔案 {file_path} 找不到，請檢查路徑或檔案")
    else:
        print(f"檔案 {file_path} 已存在")

    excel_data = pd.read_excel(file_path)
    excel_data.columns = ['chip_number', 'pet_name', 'pet_type', 'gender', 'breed', 'color', 'appearance', 
                          'features', 'lost_date', 'lost_location', 'latitude', 'longitude', 
                          'owner_name', 'contact_phone', 'email', 'photo_url','ad_content']

     # 將 NaN 值轉換為 None
    excel_data = excel_data.where(pd.notnull(excel_data), None)
    
    # 將資料插入 MySQL
    for _, row in excel_data.iterrows():
        pet = PetLost(
            chip_number=row['chip_number'],
            pet_name=row['pet_name'],
            pet_type=row['pet_type'],
            gender=row['gender'],
            breed=row['breed'],
            color=row['color'],
            appearance=row['appearance'],
            features=row['features'],
            lost_date=row['lost_date'],
            lost_location=row['lost_location'],
            latitude=row['latitude'],
            longitude=row['longitude'],
            owner_name=row['owner_name'],
            contact_phone=row['contact_phone'],
            email=row['email'],
            photo_url=row['photo_url'],
            ad_content=row['ad_content'] if pd.notnull(row['ad_content']) else None,  # 處理 ad_content 欄位
        )
        session.add(pet)

    try:
        session.commit()
        print("資料已成功匯入。")
    except Exception as e:
        session.rollback()
        print(f"資料匯入錯誤: {e}")
    finally:
        session.close()

# 初始化資料庫和匯入資料
initialize_database()

# MySQL 資料庫連接配置
db = mysql.connector.connect(
    host=DB_HOST,
    user=DB_USER,
    password=DB_PASSWORD,
    database=DB_NAME,
)

# 3. 建立 Flask 應用和 API
app = Flask(__name__)
app.secret_key = "any string"  # 設定密鑰

# 確保存在上傳目錄
UPLOAD_FOLDER = 'static/uploads'  # 上傳的照片保存路徑
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER  # 將上傳目錄加入 Flask 配置
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 全局經緯度變數
location_data = {}

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/', methods=['GET', 'POST'])
def index():
    return render_template("index.html", API_KEY=API_KEY)

@app.route('/ad-post')
def ad_post():
    if request.method == 'POST':
        # 將表單數據保存到 session 中
            session['pet_name'] = request.form.get('pet_name')
            session['lost_date'] = request.form.get('lost_date')
            session['lost_location'] = request.form.get('lost_location')
            session['features'] = request.form.get('features')
            session['contact_phone'] = request.form.get('contact_phone')

            print("Session data after post:", session)

    return render_template("ad-post.html")

# API 路徑：獲取 pet_lost 表的數據

# 建立全域變數以存儲經緯度
location_data = {}

@app.route('/templates', methods=['POST', 'GET'])
def templates():
    global location_data
    if request.method == 'POST':
        # 檢查是否為 JSON 請求（只包含經緯度）
        if request.is_json:
            data = request.get_json()
            location_data['latitude'] = data.get('latitude')
            location_data['longitude'] = data.get('longitude')
            return jsonify({'status': '經緯度已儲存'}), 200
        else:
            # 處理表單資料提交
            pet_name = request.form.get("pet_name")
            lost_date = request.form.get("lost_date")
            lost_location = request.form.get("lost_location")
            features = request.form.get("features")
            contact_phone = request.form.get("contact_phone")
            latitude = location_data.get('latitude')
            longitude = location_data.get('longitude')
            ad_content = request.form.get('ad_content')

            
            # 正確獲取上傳的圖片檔案
            picture = request.files.get('photo_url')
            if picture and allowed_file(picture.filename):
                
                # 使用 secure_filename 來獲取安全的檔案名稱
                photo_filename = secure_filename(picture.filename)
            
            
                # 儲存檔案到伺服器
                picture_path = os.path.join(app.config['UPLOAD_FOLDER'], photo_filename)  # 修正為正確的路徑
                try:
                    picture.save(picture_path)  # 保存到 static/uploads
                    print(f"檔案成功保存到: {picture_path}")  # 偵錯訊息
                except Exception as e:
                    print(f"儲存檔案時出現錯誤: {e}")  # 偵錯訊息
                    return jsonify({'error': '儲存檔案時出現錯誤'}), 500
                
                # 設定圖片的相對路徑
                photo_url = f'/static/uploads/{photo_filename}'  # 設定正確的相對路徑
                
                # 儲存到資料庫
                cursor = db.cursor()
                sql = """
                INSERT INTO pet_lost (pet_name, lost_date, lost_location, features, latitude, longitude, contact_phone, photo_url,ad_content) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s,%s)
                """
                values = (pet_name, lost_date, lost_location, features, latitude, longitude, contact_phone, photo_url,ad_content)
                cursor.execute(sql, values)
                db.commit()
                session['id'] = cursor.lastrowid 
                cursor.close()

                session['photo_url'] = photo_url
                print("資料連線成功")

        session['pet_name'] = request.form.get('pet_name')
        session['lost_date'] = request.form.get('lost_date')
        session['lost_location'] = request.form.get('lost_location')
        session['features'] = request.form.get('features')
        session['contact_phone'] = request.form.get('contact_phone')

        print("Session data after post:", session)

            # 調用 AI 生成功能
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": f"""根據以下資訊，生成一段簡短的尋寵廣告文案，必須包括下面資訊，並每次都要生成跟內容相關的不同描述，字數最多50字和最多5行：
            寵物名稱：{session['pet_name']}
            失蹤時間：{session['lost_date']}
            失蹤地點：{session['lost_location']}
            寵物特徵：{session['features']}
            聯絡電話：{session['contact_phone']} """}
            ]
        )
        session['ad_content'] = response['choices'][0]['message']['content'].strip()

    return render_template('template.html', **session)
    

@app.route('/nodify', methods=['GET', 'POST'])
def nodify():
    if request.method == 'POST':
        # 獲取更新後的文案
        updated_ad_content = request.form.get('ad_content')
        session['ad_content'] = updated_ad_content

        # 確保更新到資料庫
        try:
            cursor = db.cursor()
            sql = """
            UPDATE pet_lost 
            SET ad_content = %s 
            WHERE id = %s
            """
            values = (updated_ad_content, session.get('id'))  # 確保 session 有正確的 id
            cursor.execute(sql, values)
            db.commit()  # 提交更改
            cursor.close()
            print("文案已成功更新至資料庫")
        except Exception as e:
            print(f"更新資料庫失敗: {e}")
            return jsonify({"error": f"更新失敗: {e}"}), 500

    return render_template('nodify.html',
        pet_name=session.get('pet_name'),
        lost_time=session.get('lost_date'),
        lost_place=session.get('lost_location'),
        feature=session.get('features'),
        telphone=session.get('contact_phone'),
        ad_content=session.get('ad_content'),
        photo_url=session.get('photo_url'),
    )

@app.route('/map', methods=['GET', 'POST'])
def map():
    return render_template('index.html')

@app.route('/adopt', methods=['GET', 'POST'])
def adopt():
    return render_template('adopt.html')

@app.route('/api/pet-lost', methods=['GET'])
def get_lost_pets():
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM pet_lost")
    results = cursor.fetchall()
    cursor.close()
    return jsonify(results)

@app.route('/api/pet-lost/delete', methods=['DELETE'])
def delete_lost_pet():
    data = request.get_json()
    lost_location = data.get('lost_location')

    if not lost_location:
        return jsonify({'error': '缺少走失地點'}), 400

    try:
        cursor = db.cursor()
        sql = "DELETE FROM pet_lost WHERE lost_location = %s"
        cursor.execute(sql, (lost_location,))
        db.commit()

        if cursor.rowcount > 0:
            return jsonify({'message': '已成功回報'}), 200
        else:
            return jsonify({'error': '未找到相關資料'}), 404

    except Exception as e:
        db.rollback()  # 如果發生錯誤，回滾交易
        return jsonify({'error': f'刪除失敗: {e}'}), 500
    finally:
        cursor.close()
        
@app.route('/get_data', methods=['GET'])
def get_data():
    response = requests.get(API_URL)
    if response.status_code == 200:
        try:
            data = response.json()
            return jsonify(data)
        except ValueError:
            return jsonify({"error": "無法解析 JSON 响應"}), 500
    else:
        return jsonify({"error": f"API 請求失敗，狀態碼: {response.status_code}"}), 500

# 啟動應用
if __name__ == '__main__':
    app.run(debug=True)

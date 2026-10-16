import os
import time
import random
from datetime import timedelta
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from flask import Flask, render_template, request, redirect, url_for
from faker import Faker

app = Flask(__name__)
fake = Faker("ru_RU")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5433")
DB_NAME = os.getenv("DB_NAME", "users_db")
DB_USER = os.getenv("DB_USER", "admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "secretpassword")


def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )


def init_and_seed_db():
    for attempt in range(10):
        try:
            conn = get_db_connection()
            break
        except psycopg2.OperationalError:
            print(f"Ожидание запуска БД PostgreSQL... (попытка {attempt + 1}/10)")
            time.sleep(2)
    else:
        raise RuntimeError("Не удалось подключиться к PostgreSQL. Проверьте Docker.")

    cursor = conn.cursor()

    # 1. Открытая таблица
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS public_users (
            id SERIAL PRIMARY KEY,
            last_name VARCHAR(100) NOT NULL,
            first_name VARCHAR(100) NOT NULL,
            patronymic VARCHAR(100) NOT NULL,
            mobile_phone VARCHAR(50) NOT NULL,
            home_phone VARCHAR(50),
            birth_date DATE NOT NULL,
            gender VARCHAR(10) NOT NULL,
            email VARCHAR(150) NOT NULL
        );
    """)

    # 2. Закрытая таблица
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sensitive_users (
            user_id INTEGER PRIMARY KEY REFERENCES public_users(id) ON DELETE CASCADE,
            passport_series VARCHAR(20) NOT NULL,
            passport_number VARCHAR(20) NOT NULL,
            last_name VARCHAR(100) NOT NULL,
            first_name VARCHAR(100) NOT NULL,
            patronymic VARCHAR(100) NOT NULL,
            birth_date DATE NOT NULL,
            birth_address TEXT NOT NULL,
            issue_date DATE NOT NULL,
            department_code VARCHAR(20) NOT NULL,
            issued_by TEXT NOT NULL,
            residence_address TEXT NOT NULL,
            has_foreign_passport BOOLEAN NOT NULL
        );
    """)

    cursor.execute("SELECT COUNT(*) FROM public_users;")
    count = cursor.fetchone()[0]

    if count == 0:
        print("Генерация 1000 записей через Faker в PostgreSQL...")
        public_data = []
        sensitive_data = []

        for i in range(1, 1001):
            gender_choice = random.choice(["М", "Ж"])
            if gender_choice == "М":
                first_name = fake.first_name_male()
                last_name = fake.last_name_male()
                patronymic = fake.middle_name_male()
            else:
                first_name = fake.first_name_female()
                last_name = fake.last_name_female()
                patronymic = fake.middle_name_female()

            birth_dt = fake.date_of_birth(minimum_age=18, maximum_age=80)
            birth_date_str = birth_dt.strftime("%Y-%m-%d")

            issue_dt = fake.date_between(
                start_date=birth_dt + timedelta(days=14 * 365),
                end_date="today"
            )
            issue_date_str = issue_dt.strftime("%Y-%m-%d")

            mobile_phone = fake.phone_number()
            home_phone = fake.phone_number() if random.choice([True, False]) else None
            email = fake.unique.email()

            passport_series = f"{random.randint(10, 99)} {random.randint(10, 99)}"
            passport_number = f"{random.randint(100000, 999999)}"
            department_code = f"{random.randint(100, 999)}-{random.randint(100, 999)}"
            issued_by = f"ГУ МВД России по г. {fake.city_name()}"
            birth_address = fake.address()
            residence_address = fake.address()
            has_foreign = random.choice([True, False])

            public_data.append((
                i, last_name, first_name, patronymic,
                mobile_phone, home_phone, birth_date_str, gender_choice, email
            ))

            sensitive_data.append((
                i, passport_series, passport_number, last_name, first_name,
                patronymic, birth_date_str, birth_address, issue_date_str,
                department_code, issued_by, residence_address, has_foreign
            ))

        execute_values(cursor, """
            INSERT INTO public_users (
                id, last_name, first_name, patronymic,
                mobile_phone, home_phone, birth_date, gender, email
            ) VALUES %s
        """, public_data)

        execute_values(cursor, """
            INSERT INTO sensitive_users (
                user_id, passport_series, passport_number, last_name, first_name,
                patronymic, birth_date, birth_address, issue_date,
                department_code, issued_by, residence_address, has_foreign_passport
            ) VALUES %s
        """, sensitive_data)

        conn.commit()
        print("База данных PostgreSQL успешно заполнена 1000 записями!")

    # Синхронизация счетчика автоинкремента SERIAL, чтобы новые записи не конфликтовали с существующими ID
    cursor.execute("SELECT setval(pg_get_serial_sequence('public_users', 'id'), COALESCE(MAX(id), 1)) FROM public_users;")
    conn.commit()

    cursor.close()
    conn.close()


@app.route("/")
def index():
    tab = request.args.get("tab", "public")
    page = int(request.args.get("page", 1))
    per_page = 50
    offset = (page - 1) * per_page

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    if tab == "sensitive":
        cursor.execute("SELECT COUNT(*) FROM sensitive_users;")
        total_count = cursor.fetchone()['count']
        cursor.execute(
            "SELECT * FROM sensitive_users ORDER BY user_id LIMIT %s OFFSET %s;",
            (per_page, offset)
        )
    else:
        cursor.execute("SELECT COUNT(*) FROM public_users;")
        total_count = cursor.fetchone()['count']
        cursor.execute(
            "SELECT * FROM public_users ORDER BY id LIMIT %s OFFSET %s;",
            (per_page, offset)
        )

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    total_pages = max(1, (total_count + per_page - 1) // per_page)

    return render_template("index.html", rows=rows, tab=tab, page=page, total_pages=total_pages)


@app.route("/add", methods=["POST"])
def add_user():
    last_name = request.form.get("last_name") or fake.last_name()
    first_name = request.form.get("first_name") or fake.first_name()
    patronymic = request.form.get("patronymic") or fake.middle_name()
    mobile_phone = request.form.get("mobile_phone") or fake.phone_number()
    home_phone = request.form.get("home_phone") or None
    gender = request.form.get("gender") or random.choice(["М", "Ж"])
    email = request.form.get("email") or fake.email()
    birth_date = request.form.get("birth_date") or fake.date_of_birth(minimum_age=18, maximum_age=80).strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Вставка в публичную таблицу (теперь ID сгенерируется автоматически через SERIAL)
    cursor.execute("""
        INSERT INTO public_users (last_name, first_name, patronymic, mobile_phone, home_phone, birth_date, gender, email)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
    """, (last_name, first_name, patronymic, mobile_phone, home_phone, birth_date, gender, email))
    
    new_id = cursor.fetchone()[0]

    # 2. Генерация чувствительных данных для закрытой таблицы
    birth_dt = fake.date_of_birth(minimum_age=18, maximum_age=80)
    issue_dt = fake.date_between(start_date=birth_dt + timedelta(days=14 * 365), end_date="today")
    
    passport_series = f"{random.randint(10, 99)} {random.randint(10, 99)}"
    passport_number = f"{random.randint(100000, 999999)}"
    department_code = f"{random.randint(100, 999)}-{random.randint(100, 999)}"
    issued_by = f"ГУ МВД России по г. {fake.city_name()}"
    birth_address = fake.address()
    residence_address = fake.address()
    has_foreign = random.choice([True, False])

    cursor.execute("""
        INSERT INTO sensitive_users (
            user_id, passport_series, passport_number, last_name, first_name,
            patronymic, birth_date, birth_address, issue_date,
            department_code, issued_by, residence_address, has_foreign_passport
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
    """, (
        new_id, passport_series, passport_number, last_name, first_name,
        patronymic, birth_date, birth_address, issue_dt.strftime("%Y-%m-%d"),
        department_code, issued_by, residence_address, has_foreign
    ))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('index', tab='public', page=1))


if __name__ == "__main__":
    init_and_seed_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
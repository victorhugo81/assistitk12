# create_env.py
import os
import secrets
import pymysql
import random
import string
from getpass import getpass

# Step 1: Prompt user input
host = input("Enter MySQL host (default: localhost): ") or "localhost"
root_user = input("Enter MySQL root username (e.g., root): ")
root_pass = getpass("Enter MySQL root password: ")

# Step 2: Generate secret key, database name, user/pass
secret_key = secrets.token_urlsafe(32)
random_prefix = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=5))
database_name = f"{random_prefix}_assistitk12"
new_db_user = f"user_{random_prefix}"
new_db_pass = secrets.token_urlsafe(16)

# Step 3: Connect to MySQL and create DB + user
try:
    connection = pymysql.connect(host=host, user=root_user, password=root_pass)
    cursor = connection.cursor()

    cursor.execute(f"CREATE DATABASE IF NOT EXISTS {database_name}")
    cursor.execute(f"CREATE USER IF NOT EXISTS '{new_db_user}'@'%' IDENTIFIED BY '{new_db_pass}'")
    cursor.execute(f"GRANT ALL PRIVILEGES ON {database_name}.* TO '{new_db_user}'@'%'")
    cursor.execute("FLUSH PRIVILEGES")

    print(f"✅ Database '{database_name}' created.")
    print(f"✅ MySQL user '{new_db_user}' created.")

except pymysql.MySQLError as e:
    print(f"❌ MySQL Error: {e}")
    exit(1)
finally:
    if connection:
        connection.close()

# Step 4: Write to .env
env_content = f"""# .env file
SECRET_KEY={secret_key}
DATABASE_URL=mysql+pymysql://{new_db_user}:{new_db_pass}@{host}/{database_name}
"""

root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
env_path = os.path.join(root_path, '.env')

if not os.path.exists(env_path):
    with open(env_path, "w") as f:
        f.write(env_content)
    print("✅ .env file created in project root.")
else:
    print("⚠️ .env already exists in project root. Skipping write.")

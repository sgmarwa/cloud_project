from flask import Flask, jsonify, render_template, request, redirect, url_for, session
from flask_session import Session
import mysql.connector
import bcrypt
import boto3
import os
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from flask_cors import CORS
from datetime import timedelta

# Charger les variables d'environnement
load_dotenv()

AWS_ACCESS_KEY = os.getenv('AWS_ACCESS_KEY')
AWS_SECRET_KEY = os.getenv('AWS_SECRET_KEY')
S3_BUCKET = os.getenv('S3_BUCKET')

# Vérification des variables essentielles
if not AWS_ACCESS_KEY or not AWS_SECRET_KEY or not S3_BUCKET:
    raise ValueError("Les variables d'environnement AWS ne sont pas correctement définies.")

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'default_secret_key')  # Clé secrète pour les sessions
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access
app.config['SESSION_COOKIE_SECURE'] = True  # Set True if using HTTPS
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # More secure default

app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

Session(app)
# CORS(app, supports_credentials=True)
CORS(app, supports_credentials=True, resources={r"/*": {"origins": "*", "methods": ["GET", "POST", "OPTIONS"]}}) # This allows all origins for all routes



# Fonction pour établir une connexion à la base de données
def get_db_connection():
    try:
        return mysql.connector.connect(
            host='dbprojectserver.cnoegm6cssqo.us-east-1.rds.amazonaws.com',
            user='admin',
            password='Marwa123',
            database='recette'
        )
    except mysql.connector.Error as err:
        raise Exception(f"Erreur de connexion à la base de données : {err}")

# Fonction pour uploader l'image sur S3
def upload_image_to_s3(image_file):
    try:
        s3 = boto3.client(
            's3',
            aws_access_key_id=AWS_ACCESS_KEY,
            aws_secret_access_key=AWS_SECRET_KEY
        )
        filename = secure_filename(image_file.filename)
        s3.upload_fileobj(image_file, S3_BUCKET, filename)
        return f'https://{S3_BUCKET}.s3.amazonaws.com/{filename}'
    except Exception as e:
        print(f"Erreur lors de l'upload sur S3: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/login', methods=['POST'])
def login():
    try:
        email = request.json.get('email')
        password = request.json.get('pswd')

        print(f"Email: {email}, Password: {password}")

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()

        if user and bcrypt.checkpw(password.encode('utf-8'), user['pswd'].encode('utf-8')):
            session['user_id'] = user['user_id']
            session.modified = True
            print(f"Session after login: {session}")
            print(f"Login successful for user_id: {user['user_id']}")
            response = jsonify({ 'message': 'Login successful','redirect_url': url_for('home', user_id=user['user_id'])  })  # Add user_id as query param
            # response = jsonify({'message': 'Login successful', 'redirect_url': url_for('home')})
            response.set_cookie('session', str(session.sid), httponly=True, secure=False, samesite='Lax')
            return response, 200
        else:
            print("Invalid login credentials")
            return jsonify({'error': 'Invalid login credentials'}), 401
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        connection.close()


@app.route('/add_recipe', methods=['GET', 'POST'])
def add_recipe():
    user_id = session.get('user_id')
    print(f"User ID from session: {user_id}")
    
    if not user_id:
        return redirect(url_for('index'))

    if request.method == 'POST':
        try:
            connection = get_db_connection()
            cursor = connection.cursor()

            recipe_name = request.form['recipeName']
            ingredients = request.form['ingredients']
            instructions = request.form['instructions']
            nb_likes = 0  # Initialize likes to 0 for a new recipe
            image = request.files['image']

            image_url = upload_image_to_s3(image)
            if not image_url:
                return "Error uploading image to S3", 500

            cursor.execute(
                "INSERT INTO recipes (user_id, name_recipe, ingredients, instructions, nb_likes, image_url) VALUES (%s, %s, %s, %s, %s, %s)",
                (user_id, recipe_name, ingredients, instructions, nb_likes, image_url)
            )
            connection.commit()
            return redirect(url_for('home'))
        except mysql.connector.Error as err:
            return f"Erreur : {err}"
        finally:
            cursor.close()
            connection.close()

    return render_template('add_recipe.html')

@app.route('/register', methods=['POST'])
def register():
    try:
        data = request.json
        first_name = data.get('first_name')
        last_name = data.get('last_name')
        email = data.get('email')
        password = data.get('pswd')

        if not all([first_name, last_name, email, password]):
            return jsonify({"error": "Tous les champs sont requis"}), 400

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            return jsonify({"error": "Email already registered"}), 400

        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        cursor.execute(
            "INSERT INTO users (first_name, last_name, email, pswd) VALUES (%s, %s, %s, %s)",
            (first_name, last_name, email, hashed_password.decode('utf-8'))
        )
        connection.commit()
        return jsonify({"message": "User registered successfully"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        connection.close()

@app.route('/home')
def home():
    user_id = request.args.get('user_id')
    if user_id:
        session['user_id'] = user_id
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT recipe_id, name_recipe, ingredients, instructions, nb_likes, image_url FROM recipes")
        recipes = cursor.fetchall()
        return render_template('home.html', recipes=recipes)
    except mysql.connector.Error as err:
        return f"Erreur : {err}"
    finally:
        cursor.close()
        connection.close()

@app.route('/recette/<int:recipe_id>')
def show_recipe(recipe_id):
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT name_recipe, ingredients, instructions, nb_likes, image_url FROM recipes WHERE recipe_id = %s", (recipe_id,))
        recipe = cursor.fetchone()

        if not recipe:
            return "Recette non trouvée", 404
        return render_template('recette.html', recipe=recipe)
    except mysql.connector.Error as err:
        return f"Erreur : {err}"
    finally:
        cursor.close()
        connection.close()



if __name__ == "__main__":
    app.run(debug=True)


# **********************************************lambda *********************************************
# lambda_client = boto3.client(
#     'lambda',
#     region_name='eu-north-1',
#     aws_access_key_id='soukabadaoui88@gmail.com',
#     aws_secret_access_key='soukainaPQ2024'
# )

# @app.route('/update-trending', methods=['GET'])
# def update_trending():
#     """Appelle la fonction Lambda pour mettre à jour les recettes trending."""
#     try:
#         response = lambda_client.invoke(
#             FunctionName='update_trending_recipes',
#             InvocationType='RequestResponse'
#         )
#         result = response['Payload'].read().decode('utf-8')
#         print("Réponse Lambda :", result)
#         return jsonify({"success": True, "result": result})
    
#     except Exception as e:
#         print("Erreur lors de l'appel à Lambda :", str(e))   
#         return jsonify({"success": False, "error": str(e)})
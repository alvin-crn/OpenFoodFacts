from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from datetime import datetime
from bson import ObjectId
import requests
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Connexion à MongoDB
client = MongoClient("mongodb+srv://admin:admin@clusterfood.kdwq6.mongodb.net/?retryWrites=true&w=majority&appName=clusterfood")
db = client['openfoodfact']
users_collection = db['users']
substitutes_collection = db["substitutes"]

# Vérifier si l'utilisateur est connecté
def is_user_logged_in():
    return 'user_data' in session

# Fonction pour récupérer les produits similaires (Nutri-Score A)
def get_similar_products(category):
    url = f"https://world.openfoodfacts.org/api/v2/search?categories_tags={category}&fields=code,image_url,product_name,brands,nutrition_grades&sort_by=nutrition_grades"
    response = requests.get(url)
    data = response.json()

    # Filtrer les produits ayant un Nutri-Score 'A'
    products = []
    for product in data['products']:
        if product.get('nutrition_grades') == 'a':  # Vérifie si le Nutri-Score est A
            products.append(product)

    return products

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/connexion', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email').strip()
        password = request.form.get('password')

        # Vérifier si l'utilisateur existe dans la base de données
        user = users_collection.find_one({'email': email})

        if user and check_password_hash(user['password'], password):
          # Stocker toutes les informations de l'utilisateur dans la session
            session['user_data'] = {
                'id': str(user['_id']),
                'username': user['username'],
                'email': user['email'],
                'allergens': user['allergens'],
                'created_at': user['created_at']
            }
            flash("Connexion réussie !")
            return redirect(url_for('home'))
        else:
            flash("Email ou mot de passe incorrect.")
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    # Supprimer les informations de la session
    session.pop('user_data', None)
    flash("Déconnexion réussie !")
    return redirect(url_for('home'))

@app.route('/inscription', methods=['GET', 'POST'])
def register():
  if request.method == 'POST':
        # Récupérer les données du formulaire
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

        # Validation simple
        if not username or not email or not password:
            flash("Tous les champs sont obligatoires !")
            return redirect(url_for('register'))

        # Vérifier si l'utilisateur existe déjà
        if users_collection.find_one({'email': email}):
            flash("Cet email est déjà utilisé !")
            return redirect(url_for('register'))

        # Insérer l'utilisateur dans la base de données
        new_user = {
            'username': username,
            'email': email,
            'password': hashed_password,
            'allergens': [],
            'created_at': datetime.now()
        }
        users_collection.insert_one(new_user)

        flash("Inscription réussie ! Vous pouvez maintenant vous connecter.")
        return redirect(url_for('home'))
  return render_template('register.html')

@app.route('/profil')
def profil():
    if 'user_data' not in session:
        flash("Vous devez être connecté pour accéder à cette page.")
        return redirect(url_for('login'))
    
    user_data = session['user_data']
    user_id = user_data['id']

    # Récupérer les allergènes depuis l'URL
    url = "https://static.openfoodfacts.org/data/taxonomies/allergens.json"
    response = requests.get(url)

    if response.status_code == 200:
        allergens_data = response.json()
        allergens_list = []

        # Extraire les allergènes en anglais (clé 'en')
        for allergen_key, allergen_info in allergens_data.items():
            if 'en' in allergen_info['name']:
                allergens_list.append(allergen_info['name']['en'])
    else:
        flash("Impossible de récupérer la liste des allergènes.")
    
    # Récupérer les substituts créés par l'utilisateur en base de données
    substitutes = list(substitutes_collection.find({"created_by_user": ObjectId(user_id)}))

    # Compléter les informations des produits depuis l'API OpenFoodFacts
    for substitute in substitutes:
        original_url = f"https://world.openfoodfacts.org/api/v2/product/{substitute['original_product_barcode']}"
        substitute_url = f"https://world.openfoodfacts.org/api/v2/product/{substitute['substitute_product_barcode']}"

        original_response = requests.get(original_url)
        substitute_response = requests.get(substitute_url)

        substitute['original_product'] = original_response.json().get('product', {})
        substitute['substitute_product'] = substitute_response.json().get('product', {})

    # Passer les données au template
    return render_template('profil.html', user_data=user_data, allergens_list=allergens_list, substitutes=substitutes)

@app.route('/delete_substitute', methods=['POST'])
def delete_substitute():
    if 'user_data' not in session:
        flash("Vous devez être connecté pour effectuer cette action.")
        return redirect(url_for('login'))
    
    substitute_id = request.form.get('substitute_id')
    if not substitute_id:
        flash("Aucun substitut spécifié.")
        return redirect(url_for('profil'))

    try:
        # Supprime le substitut de la base de données
        substitutes_collection.delete_one({"_id": ObjectId(substitute_id)})
        flash("Substitut supprimé avec succès.")
    except Exception as e:
        flash("Erreur lors de la suppression du substitut.")
    
    return redirect(url_for('profil'))

@app.route('/add_allergen', methods=['POST'])
def add_allergen():
    if 'user_data' not in session:
        flash("Vous devez être connecté pour effectuer cette action.")
        return redirect(url_for('login'))

    user_data = session['user_data']
    new_allergen = request.form.get('new_allergen')

    # Convertir l'ID de l'utilisateur en ObjectId
    user_id = ObjectId(user_data['id'])

    # Ajouter l'allergène à la liste de l'utilisateur dans la base de données
    result = users_collection.update_one(
        {'_id': user_id},  # Utilisation de ObjectId pour l'ID
        {'$addToSet': {'allergens': new_allergen}}  # Utilisation de $addToSet pour éviter les doublons
    )

    # Vérifier si la mise à jour a réussi
    if result.acknowledged and result.modified_count > 0:
        user_data['allergens'].append(new_allergen)  # Ajouter à la session
        session['user_data'] = user_data
        flash(f"Allergène '{new_allergen}' ajouté avec succès !")
    elif result.matched_count == 0:
        flash(f"Aucun utilisateur trouvé avec cet identifiant.")
    else:
        flash(f"L'allergène '{new_allergen}' existe déjà ou la mise à jour a échoué.")

    return redirect(url_for('profil'))

@app.route('/remove_allergen/<string:allergen_name>')
def remove_allergen(allergen_name):
    if 'user_data' not in session:
        flash("Vous devez être connecté pour effectuer cette action.")
        return redirect(url_for('login'))

    user_data = session['user_data']

    # Convertir l'ID de l'utilisateur en ObjectId
    user_id = ObjectId(user_data['id'])

    # Supprimer l'allergène de la base de données
    result = users_collection.update_one(
        {'_id': user_id},  # Utilisation de ObjectId pour l'ID
        {'$pull': {'allergens': allergen_name}}  # Utilisation de $pull pour supprimer l'allergène
    )

    # Vérifier si la suppression a réussi
    if result.acknowledged and result.modified_count > 0:
        user_data['allergens'].remove(allergen_name)  # Supprimer de la session
        session['user_data'] = user_data
        flash(f"Allergène '{allergen_name}' supprimé avec succès !")
    elif result.matched_count == 0:
        flash(f"Aucun utilisateur trouvé avec cet identifiant.")
    else:
        flash(f"L'allergène '{allergen_name}' n'a pas pu être supprimé.")

    return redirect(url_for('profil'))

@app.route('/les-produits', methods=['GET', 'POST'])
def products():
    results = []
    search_type = request.form.get('search_type')
    query = request.form.get('query')

    if request.method == 'POST' and query:
        if search_type == 'code':  # Recherche par code-barres
            url = f"https://world.openfoodfacts.net/api/v2/product/{query}?fields=product_name,categories,ingredients_text,allergens_tags,nutriscore_data,nova_group,ecoscore,stores_tags,image_url,url,nutriments,code"
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 1:  # Produit trouvé
                    product = data['product']
                    results = [product]  
                else:
                    flash("Aucun produit trouvé pour ce code-barres.")
            else:
                flash("Erreur lors de la recherche par code-barres.")

        elif search_type == 'name':  # Recherche par nom
            url = f"https://world.openfoodfacts.net/cgi/search.pl?search_terms={query}&action=process&json=true&fields=product_name,categories,ingredients_text,allergens_tags,nutriscore_data,nova_group,ecoscore,stores_tags,image_url,url,nutriments,code"
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                results = data.get('products', [])
            else:
                flash("Erreur lors de la recherche par nom.")

        elif search_type == 'category':  # Recherche par catégorie
            url = f"https://world.openfoodfacts.org/category/{query}.json"
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                results = data.get('products', [])
            else:
                flash("Erreur lors de la recherche par catégorie.")

    return render_template('product.html', results=results, search_type=search_type, query=query)

# Route pour afficher un produit avec ses substituts
@app.route('/product/<product_code>', methods=['GET'])
def product_detail(product_code):
    # Récupérer les informations du produit de base
    product_url = f"https://world.openfoodfacts.org/api/v2/product/{product_code}"
    product_response = requests.get(product_url)
    product_data = product_response.json()

    product = product_data.get('product', {})
    category = product.get('categories_tags', [])[0]  # Récupérer la première catégorie
    similar_products = get_similar_products(category)  # Récupérer les produits similaires

    return render_template('product_detail.html', product=product, similar_products=similar_products)

# Route pour ajouter un substitut (ajouter un produit dans la base de données)
@app.route('/add_substitute', methods=['POST'])
def add_substitute():

    # Vérifier si l'utilisateur est connecté
    if not is_user_logged_in():
        return redirect(url_for('login'))  # Redirige vers la page de connexion si non connecté

    # Récupérer les données du formulaire
    original_product_barcode = request.form['original_product_barcode']
    substitute_product_barcode = request.form['substitute_product_barcode']
    
    # Récupérer l'ID de l'utilisateur connecté
    created_by_user = session['user_data']['id']
    created_by_user = ObjectId(created_by_user)

    # Créer l'objet substitut à insérer dans la base de données
    substitute_data = {
        "original_product_barcode": original_product_barcode,
        "substitute_product_barcode": substitute_product_barcode,
        "created_by_user": created_by_user,
        "created_at": datetime.now()
    }

    # Ajouter le substitut en base de données
    substitutes_collection.insert_one(substitute_data)

    # Rediriger vers la page du produit substitut
    return redirect(url_for('product_detail', product_code=substitute_product_barcode))

if __name__ == '__main__':
    app.run(debug=True)
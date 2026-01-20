# =====================
# IMPORTS
# =====================
import os
import sqlite3
import requests
import uuid
from datetime import datetime

from flask import (
    Flask, render_template, request,
    redirect, session, url_for, flash
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps


# =====================
# APP CONFIG
# =====================
app = Flask(__name__)
app.secret_key = "streetlab-secret"

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database", "database.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# =====================
# DATABASE
# =====================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def ensure_users_columns():
    db = get_db()

    columns = db.execute("PRAGMA table_info(users)").fetchall()
    column_names = [col["name"] for col in columns]

    if "created_at" not in column_names:
        db.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
        db.commit()

    db.close()

# =====================
# TABLES
# =====================
def create_users_table():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'user'
            
        )
    """)
    db.commit()
    db.close()


def create_products_table():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            price REAL NOT NULL,
            description TEXT,
            category TEXT,
            image TEXT,
            active INTEGER DEFAULT 1
        )
    """)
    db.commit()
    db.close()


def create_product_stock_table():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS product_stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            size TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        )
    """)
    db.commit()
    db.close()


def create_orders_table():
    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE,
            created_at TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            customer_email TEXT NOT NULL,
            address_line TEXT NOT NULL,
            address_city TEXT NOT NULL,
            address_state TEXT NOT NULL,
            address_zip TEXT NOT NULL,
            payment_method TEXT NOT NULL,
            subtotal REAL NOT NULL,
            shipping REAL NOT NULL,
            total REAL NOT NULL,
            status TEXT DEFAULT 'pending'
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            size TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY(product_id) REFERENCES products(id)
        )
    """)

    db.commit()
    db.close()


# =====================
# INIT DATABASE
# =====================
# =====================
# INIT DATABASE
# =====================
create_users_table()
create_products_table()
create_product_stock_table()
create_orders_table()

ensure_users_columns()



# =====================
# HELPERS
# =====================


def calculate_shipping_by_state(state: str):
    state = state.upper().strip()

    if state == "SP":
        return 15.00

    sudeste = ["RJ", "MG", "ES"]
    sul_centro = ["PR", "SC", "RS", "MS", "MT", "GO", "DF"]
    norte_nordeste = [
        "AC","AL","AM","AP","BA","CE","MA","PA","PB",
        "PE","PI","RN","RO","RR","SE","TO"
    ]

    if state in sudeste:
        return 29.00
    if state in sul_centro:
        return 35.00
    if state in norte_nordeste:
        return 45.00

    return 39.00  # fallback
@app.context_processor
def inject_cart_count():
    cart = session.get("cart", [])
    total_items = sum(item["quantity"] for item in cart)
    return dict(cart_count=total_items)


def get_cart():
    if "cart" not in session:
        session["cart"] = []
    return session["cart"]


def is_logged():
    return "user_id" in session


def admin_required():
    return "user_id" in session and session.get("role") == "admin"


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def sanitize_cart():
    cart = session.get("cart", [])
    if not cart:
        return

    db = get_db()
    new_cart = []

    try:
        for item in cart:
            p = db.execute(
                "SELECT id, name, price, image, active FROM products WHERE id = ?",
                (item["product_id"],)
            ).fetchone()

            if not p or int(p["active"]) != 1:
                continue

            s = db.execute(
                "SELECT quantity FROM product_stock WHERE product_id = ? AND size = ?",
                (item["product_id"], item["size"])
            ).fetchone()

            if not s or int(s["quantity"]) <= 0:
                continue

            qty = min(int(item["quantity"]), int(s["quantity"]))
            if qty <= 0:
                continue

            new_cart.append({
                "product_id": p["id"],
                "name": p["name"],
                "price": float(p["price"]),
                "image": p["image"],
                "size": item["size"],
                "quantity": qty
            })
    finally:
        db.close()

    session["cart"] = new_cart
    session.modified = True





def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Faça login para continuar.")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped



# =====================
# ROUTES – PUBLIC
# =====================
@app.route("/")
def home():
    db = get_db()
    featured = db.execute(
        "SELECT * FROM products WHERE active = 1 ORDER BY id DESC LIMIT 4"
    ).fetchall()
    db.close()

    return render_template(
        "home.html",
        featured_products=featured,
        logged=is_logged(),
        user_name=session.get("user_name")
    )


# =====================
# AUTH
# =====================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password_raw = request.form.get("password", "")

        if not name or not email or not password_raw:
            flash("Preencha todos os campos.")
            return redirect("/register")

        password = generate_password_hash(password_raw)

        db = get_db()
        try:
            db.execute("""
                INSERT INTO users (name, email, password, role, created_at)
                VALUES (?, ?, ?, 'user', ?)
            """, (name, email, password, datetime.now().isoformat(timespec="seconds")))
            db.commit()
        except sqlite3.IntegrityError:
            flash("Email já cadastrado.")
            return redirect("/register")
        finally:
            db.close()

        return redirect("/login")

    return render_template("register.html")



@app.route("/login", methods=["GET", "POST"])
def login():
    next_page = request.args.get("next")

    if request.method == "POST":
        next_page = request.form.get("next") or next_page

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE email = ?",
            (request.form["email"].strip().lower(),)
        ).fetchone()
        db.close()

        if not user or not check_password_hash(user["password"], request.form["password"]):
            flash("Login inválido.")
            return redirect("/login")

        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["role"] = user["role"]

        return redirect(next_page or "/")

    return render_template("login.html", next_page=next_page)



@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# =====================
# CART
# =====================
@app.route("/cart")
@login_required
def cart():
    sanitize_cart()
    cart = get_cart()
    total = sum(i["price"] * i["quantity"] for i in cart)

    return render_template(
        "cart.html",
        cart=cart,
        total=total,
        logged=is_logged(),
        user_name=session.get("user_name")
    )


# =====================
# CHECKOUT
# =====================
@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    sanitize_cart()
    cart = session.get("cart", [])

    if not cart:
        flash("Seu carrinho está vazio.")
        return redirect("/shop")

    subtotal = sum(float(i["price"]) * int(i["quantity"]) for i in cart)

    shipping = session.get("shipping", 0.0)
    total = round(subtotal + float(shipping), 2)

    show_payment = bool(shipping and shipping > 0)

    if request.method == "POST":
        action = request.form.get("action")

        # 1) Calcular frete
        if action == "calc_shipping":
            address_state = (request.form.get("address_state") or "").strip().upper()
            if not address_state:
                flash("Informe o estado para calcular o frete.")
                return redirect("/checkout")

            shipping = float(calculate_shipping_by_state(address_state))
            session["shipping"] = shipping
            total = round(subtotal + shipping, 2)
            show_payment = True

            return render_template(
                "checkout.html",
                cart=cart,
                subtotal=subtotal,
                shipping=shipping,
                total=total,
                show_payment=show_payment,
                logged=is_logged(),
                user_name=session.get("user_name")
            )

        # 2) Finalizar pedido
        if action == "finish_order":
            shipping = float(session.get("shipping", 0.0))
            if shipping <= 0:
                flash("Calcule o frete antes de escolher o pagamento.")
                return redirect("/checkout")

            customer_name = request.form.get("customer_name", "").strip()
            customer_email = request.form.get("customer_email", "").strip().lower()
            address_line = request.form.get("address_line", "").strip()
            address_city = request.form.get("address_city", "").strip()
            address_state = request.form.get("address_state", "").strip().upper()
            address_zip = request.form.get("address_zip", "").strip()
            payment_method = request.form.get("payment_method")

            if not all([customer_name, customer_email, address_line, address_city, address_state, address_zip, payment_method]):
                flash("Preencha todos os campos e escolha o método de pagamento.")
                return redirect("/checkout")

            token = session.get("order_token") or str(uuid.uuid4())
            session["order_token"] = token

            total = round(subtotal + shipping, 2)

            db = get_db()
            try:
                # (Opcional, mas recomendado) revalidar estoque antes de fechar
                for item in cart:
                    st = db.execute(
                        "SELECT quantity FROM product_stock WHERE product_id=? AND size=?",
                        (item["product_id"], item["size"])
                    ).fetchone()
                    if not st or int(st["quantity"]) < int(item["quantity"]):
                        raise ValueError(f"Sem estoque suficiente para {item['name']} ({item['size']}).")

                cur = db.execute("""
                    INSERT INTO orders (
                        token, created_at, customer_name, customer_email,
                        address_line, address_city, address_state, address_zip,
                        payment_method, subtotal, shipping, total, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """, (
                    token,
                    datetime.now().isoformat(timespec="seconds"),
                    customer_name, customer_email,
                    address_line, address_city, address_state, address_zip,
                    payment_method,
                    float(subtotal), float(shipping), float(total)
                ))

                order_id = cur.lastrowid

                for item in cart:
                    db.execute("""
                        INSERT INTO order_items (order_id, product_id, size, quantity, unit_price)
                        VALUES (?, ?, ?, ?, ?)
                    """, (order_id, item["product_id"], item["size"], int(item["quantity"]), float(item["price"])))

                    db.execute("""
                        UPDATE product_stock
                        SET quantity = quantity - ?
                        WHERE product_id = ? AND size = ?
                    """, (int(item["quantity"]), item["product_id"], item["size"]))

                db.commit()

            except Exception as e:
                db.rollback()
                flash(str(e))
                return redirect("/checkout")
            finally:
                db.close()

            session["cart"] = []
            session.pop("order_token", None)
            session.pop("shipping", None)
            session.modified = True

            return redirect(url_for("order_success", order_id=order_id))

    return render_template(
        "checkout.html",
        cart=cart,
        subtotal=subtotal,
        shipping=shipping,
        total=total,
        show_payment=show_payment,
        logged=is_logged(),
        user_name=session.get("user_name")
    )





@app.route("/shop")
def shop():
    category = request.args.get("category")

    db = get_db()

    if category:
        products = db.execute("""
            SELECT *
            FROM products
            WHERE active = 1 AND category = ?
            ORDER BY id DESC
        """, (category,)).fetchall()
    else:
        products = db.execute("""
            SELECT *
            FROM products
            WHERE active = 1
            ORDER BY id DESC
        """).fetchall()

    db.close()

    return render_template(
        "shop.html",
        products=products,
        current_category=category,
        logged=is_logged(),
        user_name=session.get("user_name")
    )

@app.route("/product/<slug>")
def product(slug):
    db = get_db()

    product = db.execute(
        "SELECT * FROM products WHERE slug = ? AND active = 1",
        (slug,)
    ).fetchone()

    if not product:
        db.close()
        return redirect("/shop")

    stock = db.execute("""
        SELECT size, quantity
        FROM product_stock
        WHERE product_id = ?
        ORDER BY CASE size
            WHEN 'P' THEN 1
            WHEN 'M' THEN 2
            WHEN 'G' THEN 3
        END
    """, (product["id"],)).fetchall()

    db.close()

    return render_template(
        "product.html",
        product=product,
        stock=stock,
        logged=is_logged(),
        user_name=session.get("user_name")
    )

@app.route("/lookbook")
def lookbook():
    return render_template(
        "lookbook.html",
        logged=is_logged(),
        user_name=session.get("user_name")
    )


@app.route("/cart/add/<slug>", methods=["POST"])
@login_required
def add_to_cart(slug):
    size = request.form.get("size")

    if not size:
        flash("Selecione um tamanho")
        return redirect(request.referrer)

    db = get_db()
    product = db.execute(
        "SELECT * FROM products WHERE slug=? AND active=1",
        (slug,)
    ).fetchone()

    if not product:
        db.close()
        return redirect("/shop")

    stock = db.execute(
        "SELECT quantity FROM product_stock WHERE product_id=? AND size=?",
        (product["id"], size)
    ).fetchone()
    db.close()

    if not stock or stock["quantity"] <= 0:
        flash("Produto sem estoque para este tamanho")
        return redirect(request.referrer)

    cart = session.get("cart", [])

    for item in cart:
        if item["product_id"] == product["id"] and item["size"] == size:
            if item["quantity"] < stock["quantity"]:
                item["quantity"] += 1
            session.modified = True
            flash("Produto adicionado ao carrinho")
            return redirect(request.referrer)

    cart.append({
        "product_id": product["id"],
        "name": product["name"],
        "price": product["price"],
        "image": product["image"],
        "size": size,
        "quantity": 1
    })

    session["cart"] = cart
    session.modified = True
    flash("Produto adicionado ao carrinho")

    # 🔥 AQUI ESTÁ O SEGREDO
    return redirect(request.referrer)

@app.route("/admin/users")
def admin_users():
    if not admin_required():
        return redirect("/login")

    db = get_db()
    users = db.execute("""
        SELECT id, name, email, role, created_at
        FROM users
        ORDER BY created_at DESC
    """).fetchall()
    db.close()

    return render_template("admin/users.html", users=users)



# ---------- ADMIN DASHBOARD ----------
@app.route("/admin")
def admin_dashboard():
    if not admin_required():
        return redirect(url_for("login", next="/admin"))

    db = get_db()
    total_products = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    active_products = db.execute("SELECT COUNT(*) FROM products WHERE active = 1").fetchone()[0]
    total_orders = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    pending_orders = db.execute("SELECT COUNT(*) FROM orders WHERE status = 'pending'").fetchone()[0]
    db.close()

    return render_template(
        "admin/dashboard.html",
        total_products=total_products,
        active_products=active_products,
        total_orders=total_orders,
        pending_orders=pending_orders
    )


# ---------- LISTAR PRODUTOS ----------
@app.route("/admin/products")
def admin_products():
    if not admin_required():
        return redirect(url_for("login", next="/admin"))

    db = get_db()
    products = db.execute("""
        SELECT * FROM products
        ORDER BY id DESC
    """).fetchall()
    db.close()

    return render_template("admin/products.html", products=products)


# ---------- NOVO PRODUTO ----------
@app.route("/admin/products/new", methods=["GET", "POST"])
def admin_new_product():
    if not admin_required():
        return redirect(url_for("login", next="/admin"))

    if request.method == "POST":
        name = request.form["name"]
        slug = request.form["slug"]
        price = float(request.form["price"])
        category = request.form["category"]
        description = request.form["description"]
        active = 1 if request.form.get("active") else 0

        image_file = request.files.get("image")
        if not image_file or not allowed_file(image_file.filename):
            flash("Imagem inválida")
            return redirect(request.url)

        filename = secure_filename(image_file.filename)
        image_file.save(os.path.join(UPLOAD_FOLDER, filename))

        stock_p = int(request.form.get("stock_p", 0))
        stock_m = int(request.form.get("stock_m", 0))
        stock_g = int(request.form.get("stock_g", 0))

        db = get_db()

        if db.execute("SELECT 1 FROM products WHERE slug = ?", (slug,)).fetchone():
            flash("Slug já existe")
            db.close()
            return redirect(request.url)

        cur = db.execute("""
            INSERT INTO products (name, slug, price, description, category, image, active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, slug, price, description, category, filename, active))

        product_id = cur.lastrowid

        for size, qty in [("P", stock_p), ("M", stock_m), ("G", stock_g)]:
            if qty > 0:
                db.execute("""
                    INSERT INTO product_stock (product_id, size, quantity)
                    VALUES (?, ?, ?)
                """, (product_id, size, qty))

        db.commit()
        db.close()

        return redirect("/admin/products")

    return render_template("admin/new_product.html")


# ---------- EDITAR PRODUTO ----------
@app.route("/admin/products/edit/<int:id>", methods=["GET", "POST"])
def admin_edit_product(id):
    if not admin_required():
        return redirect(url_for("login", next="/admin"))

    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id = ?", (id,)).fetchone()

    if not product:
        db.close()
        return redirect("/admin/products")

    stock = db.execute("""
        SELECT size, quantity
        FROM product_stock
        WHERE product_id = ?
    """, (id,)).fetchall()

    if request.method == "POST":
        name = request.form["name"]
        price = float(request.form["price"])
        category = request.form["category"]
        description = request.form["description"]
        active = 1 if request.form.get("active") else 0
        image = product["image"]

        image_file = request.files.get("image")
        if image_file and image_file.filename:
            if not allowed_file(image_file.filename):
                flash("Formato de imagem inválido")
                return redirect(request.url)

            filename = secure_filename(image_file.filename)
            image_file.save(os.path.join(UPLOAD_FOLDER, filename))
            image = filename

        db.execute("""
            UPDATE products
            SET name=?, price=?, description=?, category=?, image=?, active=?
            WHERE id=?
        """, (name, price, description, category, image, active, id))

        for size in ["P", "M", "G"]:
            raw_qty = request.form.get(f"stock_{size.lower()}", "").strip()
            qty = int(raw_qty) if raw_qty.isdigit() else 0
            exists = db.execute("""
                SELECT id FROM product_stock
                WHERE product_id=? AND size=?
            """, (id, size)).fetchone()

            if exists:
                db.execute("""
                    UPDATE product_stock
                    SET quantity=?
                    WHERE product_id=? AND size=?
                """, (qty, id, size))
            else:
                if qty > 0:
                    db.execute("""
                        INSERT INTO product_stock (product_id, size, quantity)
                        VALUES (?, ?, ?)
                    """, (id, size, qty))

        db.commit()
        db.close()

        return redirect("/admin/products")

    db.close()
    return render_template("admin/edit_product.html", product=product, stock=stock)


# ---------- DELETAR PRODUTO ----------
@app.route("/admin/products/delete/<int:id>")
def admin_delete_product(id):
    if not admin_required():
        return redirect(url_for("login", next="/admin"))

    db = get_db()
    db.execute("DELETE FROM product_stock WHERE product_id = ?", (id,))
    db.execute("DELETE FROM products WHERE id = ?", (id,))
    db.commit()
    db.close()

    return redirect("/admin/products")


# ---------- PEDIDOS ----------
@app.route("/admin/orders")
def admin_orders():
    if not admin_required():
        return redirect(url_for("login", next="/admin"))

    db = get_db()
    orders = db.execute("""
        SELECT *
        FROM orders
        ORDER BY created_at DESC
    """).fetchall()
    db.close()

    return render_template("admin/orders.html", orders=orders)


# ---------- DETALHE DO PEDIDO ----------
@app.route("/admin/orders/<int:order_id>")
def admin_order_detail(order_id):
    if not admin_required():
        return redirect(url_for("login", next="/admin"))

    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    items = db.execute("""
        SELECT oi.*, p.name
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        WHERE oi.order_id=?
    """, (order_id,)).fetchall()
    db.close()

    if not order:
        return redirect("/admin/orders")

    return render_template(
        "admin/order_detail.html",
        order=order,
        items=items
    )


# ---------- ATUALIZAR STATUS DO PEDIDO ----------
@app.route("/admin/orders/<int:order_id>/status", methods=["POST"])
def admin_update_order_status(order_id):
    if not admin_required():
        return redirect(url_for("login", next="/admin"))

    status = request.form.get("status")

    db = get_db()
    db.execute("""
        UPDATE orders
        SET status=?
        WHERE id=?
    """, (status, order_id))
    db.commit()
    db.close()

    return redirect(url_for("admin_order_detail", order_id=order_id))


@app.route("/cart/increase/<int:index>")
@login_required
def cart_increase(index):
    cart = session.get("cart", [])

    if index >= len(cart):
        return redirect("/cart")

    item = cart[index]

    db = get_db()
    stock = db.execute(
        "SELECT quantity FROM product_stock WHERE product_id=? AND size=?",
        (item["product_id"], item["size"])
    ).fetchone()
    db.close()

    if stock and item["quantity"] < stock["quantity"]:
        item["quantity"] += 1
        session.modified = True

    return redirect("/cart")


@app.route("/cart/decrease/<int:index>")
@login_required

def cart_decrease(index):
    cart = session.get("cart", [])

    if index >= len(cart):
        return redirect("/cart")

    if cart[index]["quantity"] > 1:
        cart[index]["quantity"] -= 1
    else:
        cart.pop(index)

    session.modified = True
    return redirect("/cart")


@app.route("/cart/remove/<int:index>")
@login_required

def cart_remove(index):
    cart = session.get("cart", [])

    if index < len(cart):
        cart.pop(index)
        session.modified = True

    return redirect("/cart")

# =====================
# RUN
# =====================
if __name__ == "__main__":
    app.run()


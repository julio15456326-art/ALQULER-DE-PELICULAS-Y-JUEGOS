from flask import Flask, render_template, request, url_for, session, redirect, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import os

app = Flask(__name__)
app.secret_key = 'mi_llave_secreta_super_segura'

# =========================================================================
# 1. CONFIGURACIÓN DE LA BASE DE DATOS
# =========================================================================
db_path = os.path.join(os.path.dirname(__file__), 'alquileres.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

app.config['UPLOAD_FOLDER'] = os.path.join('static', 'img')


# =========================================================================
# 2. MODELOS DE CLASES (POO PERSISTENTE CON SQLALCHEMY)
# =========================================================================

# Clase que maneja el registro y los datos de las cuentas de usuarios (Clientes y Administrador)
class Usuario(db.Model):
    __tablename__ = 'usuarios'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    rol = db.Column(db.String(20), default='cliente') # 'cliente' o 'admin'

    # Método de instancia: Guarda el usuario actual en la base de datos relacional
    def guardar(self):
        db.session.add(self)
        db.session.commit()

    # Método de clase: Busca en la base de datos si existe un usuario con ese email y contraseña
    @classmethod
    def autenticar(cls, email_f, pass_f):
        return cls.query.filter_by(email=email_f, password=pass_f).first()


# SUPERCLASE (CLASE PADRE): Contiene todos los atributos y comportamientos comunes del catálogo [cite: 11, 109]
class ProductoAlquiler(db.Model):
    __tablename__ = 'productos_alquiler'
    
    id = db.Column(db.Integer, primary_key=True)                 
    titulo = db.Column(db.String(100), nullable=False)            
    genero = db.Column(db.String(50), nullable=True)              
    alquilado = db.Column(db.Boolean, default=False)              
    precio_alquiler = db.Column(db.Float, nullable=False)         
    
    # Atributos adicionales para la gestión interna de la aplicación web
    stock = db.Column(db.Integer, default=1)
    imagen = db.Column(db.String(100), default='default.jpg')
    tipo = db.Column(db.String(50), nullable=False)               

    # Columnas específicas de las clases hijas (mapeadas mediante Herencia)
    formato = db.Column(db.String(50), nullable=True)             
    plataforma = db.Column(db.String(50), nullable=True)          

    # SOLUCIÓN AL ERROR: El padre ahora sabe responder de forma segura a las llamadas del HTML
    def obtener_formato(self):
        """ Devuelve el formato si existe, ideal para evitar errores en las plantillas """
        return self.formato if self.formato else "No aplica"

    def obtener_plataforma(self):
        """ Devuelve la plataforma si existe, garantizando compatibilidad en las vistas """
        return self.plataforma if self.plataforma else "No aplica"

    # Método de negocio: Reduce el stock disponible y cambia el estado a "Alquilado" si corresponde
    def alquilar(self):
        if self.stock > 0:
            self.stock -= 1
            if self.stock == 0:
                self.alquilado = True                             
            db.session.commit()
            return True
        return False

    # Método de negocio: Incrementa el stock al retornar el artículo y lo vuelve a dejar disponible
    def devolver(self):
        self.stock += 1
        self.alquilado = False                                    
        db.session.commit()
        return True


# SUBCLASE (CLASE HIJA): Hereda del ProductoAlquiler genérico
class Pelicula(ProductoAlquiler):
    pass


# SUBCLASE (CLASE HIJA): Hereda del ProductoAlquiler genérico
class Juego(ProductoAlquiler):
    pass

# =========================================================================
# CLASE DE CONTROL: GESTOR DE INVENTARIO (RELACIÓN DE AGREGACIÓN) [cite: 109]
# =========================================================================

# Clase Controladora: Encapsula la gestión completa del catálogo de productos y reportes de la tienda [cite: 102, 109]
class GestorInventario:
    
    # Método estático: Inserta un nuevo objeto (Película o Juego) de forma persistente en la base de datos [cite: 11, 82, 104]
    @staticmethod
    def agregar_producto(producto):
        db.session.add(producto)
        db.session.commit()

    # Método estático: Remueve físicamente un producto del sistema utilizando su ID [cite: 11, 104]
    @staticmethod
    def eliminar_producto(id_prod):
        prod = ProductoAlquiler.query.get(id_prod)
        if prod:
            db.session.delete(prod)
            db.session.commit()
            return True
        return False

    # Método estático: Realiza una búsqueda directa en el catálogo utilizando la clave primaria [cite: 72, 105]
    @staticmethod
    def buscar_producto_por_id(id_prod):
        return ProductoAlquiler.query.get(id_prod)

    # Método estático: Filtra los productos que tienen stock disponible para mostrar en la web del cliente [cite: 51, 106]
    @staticmethod
    def listar_disponibles(tipo_prod):
        return ProductoAlquiler.query.filter_by(tipo=tipo_prod, alquilado=False).order_by(ProductoAlquiler.genero).all()

    # Método estático: Filtra los artículos que se encuentran completamente rentados por los clientes [cite: 51, 107]
    @staticmethod
    def listar_alquilados(tipo_prod):
        return ProductoAlquiler.query.filter_by(tipo=tipo_prod, alquilado=True).all()

    # Método de negocio / Módulo Financiero (RF-05): Calcula las ganancias sumando el precio de lo alquilado [cite: 51, 79, 80, 108]
    @staticmethod
    def calcular_ingresos_estimados():
        productos_rentados = ProductoAlquiler.query.filter_by(alquilado=True).all()
        return sum(p.precio_alquiler for p in productos_rentados)


# =========================================================================
# 3. RUTAS DE LA APLICACIÓN (CONTROLADORES DE VISTAS WEB FLASK) [cite: 18, 22]
# =========================================================================

# Ruta principal (Home): Muestra el catálogo de películas y videojuegos disponibles al público [cite: 18, 24]
@app.route('/')
def inicio():
    peliculas = GestorInventario.listar_disponibles('pelicula')
    juegos = GestorInventario.listar_disponibles('juego')
    return render_template('inicio.html', peliculas=peliculas, juegos=juegos)


# Ruta de Autenticación: Procesa el formulario de inicio de sesión de usuarios y administradores [cite: 18, 24]
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = Usuario.autenticar(request.form.get('email'), request.form.get('password'))
        if user:
            session['usuario_id'], session['usuario_nombre'], session['usuario_rol'] = user.id, user.nombre, user.rol
            flash(f"¡Hola, {user.nombre}!", "success") 
            return redirect(url_for('inicio'))
        flash("Credenciales incorrectas", "danger")
    return render_template('login.html')


# Ruta de Cierre de Sesión: Limpia las variables de entorno guardadas en las cookies del navegador
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('inicio'))


# Ruta Operativa de Negocio: Ejecuta la acción inmediata de alquilar reduciendo el stock disponible [cite: 73, 77]
@app.route('/alquilar/<int:prod_id>')
def alquilar_item(prod_id):
    producto = GestorInventario.buscar_producto_por_id(prod_id)
    if producto and producto.alquilar():
        flash(f"Alquilaste '{producto.titulo}' con éxito.", "success")
    else:
        flash("No hay stock disponible.", "danger")
    return redirect(url_for('inicio'))


# =========================================================================
# 4. PANEL DE CONTROL (ADMINISTRACIÓN DEL CATÁLOGO Y REPORTES)
# =========================================================================

@app.route('/admin/dashboard', methods=['GET', 'POST'])
def dashboard():
    # Validación de Seguridad: Bloquea el acceso si no sos admin
    if session.get('usuario_rol', 'cliente') != 'admin':
        flash("Acceso denegado. Se requieren permisos de Administrador.", "danger")
        return redirect(url_for('inicio'))

    if request.method == 'POST':
        tipo_f = request.form.get('tipo') 
        titulo = request.form.get('titulo')
        precio = float(request.form.get('precio'))
        stock = int(request.form.get('stock', 1))
        genero = request.form.get('genero')
        
        # 1. CAPTURA DEL ARCHIVO DESDE LA VENTANA DE TU COMPUTADORA
        file_imagen = request.files.get('imagen')
        
        if file_imagen and file_imagen.filename != '':
            # Limpiamos el nombre original (ej: "foto de peli 1.jpg" -> "foto_de_peli_1.jpg")
            nombre_imagen = secure_filename(file_imagen.filename)
            
            # Construimos la ruta de la carpeta de destino (static/img)
            carpeta_destino = os.path.join(app.root_path, app.config['UPLOAD_FOLDER'])
            
            # CONTROL DE SEGURIDAD: Si la carpeta "static/img" no existe en tu compu, la creamos al vuelo
            if not os.path.exists(carpeta_destino):
                os.makedirs(carpeta_destino)
            
            # Definimos la ruta completa con el nombre del archivo incluido
            ruta_final_archivo = os.path.join(carpeta_destino, nombre_imagen)
            
            # Guardamos físicamente el archivo seleccionado en tu computadora
            file_imagen.save(ruta_final_archivo)
        else:
            # Si el administrador no seleccionó ningún archivo, usa una por defecto
            nombre_imagen = "default.jpg"

        # 2. POLIMORFISMO: Instanciamos según corresponda pasándole el nombre de la imagen guardada
        if tipo_f == 'pelicula':
            nuevo = Pelicula(titulo=titulo, precio_alquiler=precio, stock=stock, genero=genero, tipo=tipo_f, imagen=nombre_imagen, formato=request.form.get('plataforma'))
        else:
            nuevo = Juego(titulo=titulo, precio_alquiler=precio, stock=stock, genero=genero, tipo=tipo_f, imagen=nombre_imagen, plataforma=request.form.get('plataforma'))

        # Guardamos en la base de datos usando el Gestor de Inventario
        GestorInventario.agregar_producto(nuevo)
        
        flash(f"¡{tipo_f.capitalize()} cargada con éxito! Imagen guardada en el servidor.", "success")
        return redirect(url_for('dashboard'))

    # Método GET: Muestra el panel con el reporte financiero unificado (RF-05)
    return render_template(
        'dashboard.html', 
        u_total=Usuario.query.count(), 
        p_total=ProductoAlquiler.query.filter_by(tipo='pelicula').count(), 
        j_total=ProductoAlquiler.query.filter_by(tipo='juego').count(), 
        ingresos=GestorInventario.calcular_ingresos_estimados()
    )
# Nueva Ruta: Registro de Usuarios Clientes
# =========================================================================
@app.route('/registro', methods=['GET', 'POST'])
def registro():
    """ Procesa el formulario de creación de nuevas cuentas para Clientes """
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        password = request.form.get('password')

        # Validación simple para evitar correos duplicados
        if Usuario.query.filter_by(email=email).first():
            flash("El correo electrónico ya está registrado.", "danger")
            return redirect(url_for('registro'))

        # Instanciamos la clase Usuario y usamos su método .guardar()
        nuevo_usuario = Usuario(nombre=nombre, email=email, password=password, rol='cliente')
        nuevo_usuario.guardar()

        flash("¡Cuenta creada con éxito! Ya podés iniciar sesión.", "success")
        return redirect(url_for('login'))

    return render_template('registro.html')


# =========================================================================
# 5. INICIALIZACIÓN AUTOMÁTICA AL ARRANCAR EL SERVIDOR
# =========================================================================
with app.app_context():
    db.create_all()  # Crea las tablas físicas en la base de datos relacional si no existen [cite: 12, 83]
    
    # Registra una cuenta de Administrador por defecto la primera vez para asegurar el acceso al sistema [cite: 58]
    if not Usuario.query.filter_by(email="admin@alquiler.com").first():
        Usuario(nombre="Admin", email="admin@alquiler.com", password="123", rol="admin").guardar()

if __name__ == '__main__':
    app.run(debug=True)
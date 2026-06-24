from flask import Flask, render_template, request, url_for, session, redirect, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from functools import wraps
from itsdangerous import URLSafeTimedSerializer
from flask_mail import Mail, Message
import os
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'mi_llave_secreta_super_segura'
ts = URLSafeTimedSerializer("CLAVE_SECRETA_PARA_EL_TOKEN")

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = 'ruben650160@gmail.com'
app.config['MAIL_PASSWORD'] = 'gwwuxyrjezjiwodr'
app.config['MAIL_DEFAULT_SENDER'] = 'ruben650160@gmail.com'

mail = Mail(app)

# =========================================================================
# CONFIGURACIÓN DE LA BASE DE DATOS
# =========================================================================
db_path = os.path.join(os.path.dirname(__file__), 'alquileres.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

app.config['UPLOAD_FOLDER'] = os.path.join('static', 'img')

# --- CONTROL DE ROLES ---
NIVELES_ACCESO = {'cliente': 1, 'empleado': 5, 'admin': 10}

def requiere_nivel(nivel_minimo):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            rol_usuario = session.get('usuario_rol', 'cliente')
            nivel_usuario = NIVELES_ACCESO.get(rol_usuario, 1)
            if nivel_usuario < nivel_minimo:
                flash("No tenés permisos suficientes para entrar acá.", "danger")
                return redirect(url_for('inicio'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Tabla intermedia para la lista de espera
lista_espera = db.Table('lista_espera',
    db.Column('usuario_id', db.Integer, db.ForeignKey('usuarios.id'), primary_key=True),
    db.Column('producto_id', db.Integer, db.ForeignKey('productos_alquiler.id'), primary_key=True)
)

# =========================================================================
# MODELOS
# =========================================================================

class Usuario(db.Model):
    __tablename__ = 'usuarios'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    rol = db.Column(db.String(20), default='cliente') 
    bloqueado = db.Column(db.Boolean, default=False)
    activo = db.Column(db.Boolean, default=False)

    # Relación con los alquileres individuales
    mis_alquileres = db.relationship('Alquiler', backref='usuario', lazy=True, cascade='all, delete-orphan')
    reservas_solicitadas = db.relationship('ProductoAlquiler', secondary=lista_espera, backref=db.backref('en_espera', lazy=True))

    def guardar(self):
        if self.password and not self.password.startswith('scrypt:'):
            self.password = generate_password_hash(self.password)
        db.session.add(self)
        db.session.commit()

    def es_staff(self):
        return self.rol in ('empleado', 'admin')

    def es_admin(self):
        return self.rol == 'admin'

    @classmethod
    def buscar_por_id(cls, usuario_id):
        return cls.query.get(usuario_id)

    #MÉTODO DE AUTENTICACIÓN
    @classmethod
    def autenticar(cls, email_f, pass_f):
        #Buscamos si el usuario existe por email
        user = cls.query.filter_by(email=email_f).first()
        if user:
            #Si ya está hasheada con scrypt
            if user.password.startswith('scrypt:'):
                if check_password_hash(user.password, pass_f):
                    return user
            #Si es texto plano o coincide directo
            elif user.password == pass_f:
                return user
        return None

    # --- MÉTODOS POO PARA EL RECUPERO DE CONTRASEÑA ---

    @staticmethod
    def generar_token_recupero(email):
        """Método Estático: Genera el token cifrado para el mail sin instanciar el objeto."""
        return ts.dumps(email, salt='recuperar-password')

    @staticmethod
    def verificar_token_recupero(token, expiration=3600):
        """Método Estático: Descifra el token y valida el tiempo de expiración (1 hora)."""
        try:
            email = ts.loads(token, salt='recuperar-password', max_age=expiration)
            return email
        except:
            return None

    def resetear_password(self, nueva_password):
        """Método de Instancia: El objeto usuario se modifica a sí mismo y persiste el cambio."""
        self.password = generate_password_hash(nueva_password)
        db.session.commit()

class ProductoAlquiler(db.Model):
    __tablename__ = 'productos_alquiler'
    
    id = db.Column(db.Integer, primary_key=True)                
    titulo = db.Column(db.String(100), nullable=False)            
    genero = db.Column(db.String(50), nullable=True)              
    alquilado = db.Column(db.Boolean, default=False)              
    precio_alquiler = db.Column(db.Float, nullable=False)         
    stock = db.Column(db.Integer, default=1)
    imagen = db.Column(db.String(100), default='default.jpg')
    contador_alquileres = db.Column(db.Integer, default=0) 
    tipo_producto = db.Column(db.String(50)) 

    # Relación con alquileres individuales
    alquileres_activos = db.relationship('Alquiler', backref='producto', lazy=True, cascade='all, delete-orphan')

    @property
    def precio(self):
        return self.precio_alquiler

    __mapper_args__ = {
        'polymorphic_on': tipo_producto,
        'polymorphic_identity': 'producto_generico'
    }

    def obtener_especifico(self):
        return "No aplica"

    def solicitar_alquiler(self, usuario):
        # Verificar si ya tiene un alquiler activo/pendiente para este producto
        ya_tiene = Alquiler.query.filter_by(usuario_id=usuario.id, producto_id=self.id).filter(
            Alquiler.estado.in_(['pendiente', 'activo', 'dev_pendiente'])
        ).first()
        if ya_tiene:
            return "ya_solicitado"

        if usuario.bloqueado:
            return "usuario_bloqueado"

        if self.stock > 0:
            self.stock -= 1
            if self.stock == 0:
                self.alquilado = True
            nuevo_alquiler = Alquiler(
                usuario_id=usuario.id,
                producto_id=self.id,
                estado='pendiente'
            )
            db.session.add(nuevo_alquiler)
            db.session.commit()
            return "pendiente"

        elif usuario not in self.en_espera:
            self.en_espera.append(usuario)
            db.session.commit()
            return "reservado"

        return "ya_esperando"

    def devolver_producto(self):
        """Compatibilidad: libera stock cuando se elimina un usuario."""
        self.stock += 1
        self.alquilado = False
        db.session.commit()


class Alquiler(db.Model):
    """Representa un alquiler individual de un producto por un usuario."""
    __tablename__ = 'alquileres_activos'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey('productos_alquiler.id'), nullable=False)
    estado = db.Column(db.String(30), default='pendiente')  # pendiente, activo, dev_pendiente
    fecha_alquiler = db.Column(db.DateTime, nullable=True)
    fecha_vencimiento = db.Column(db.DateTime, nullable=True)

    def esta_vencido(self):
        if self.fecha_vencimiento and datetime.now() > self.fecha_vencimiento:
            return True
        return False

    def confirmar(self):
        if self.estado != 'pendiente':
            return False
        self.estado = 'activo'
        self.fecha_alquiler = datetime.now()
        self.fecha_vencimiento = datetime.now() + timedelta(days=7)
        self.producto.contador_alquileres += 1
        db.session.commit()
        return True

    def rechazar(self):
        if self.estado != 'pendiente':
            return False
        self.producto.stock += 1
        self.producto.alquilado = False
        db.session.delete(self)
        db.session.commit()
        return True

    def solicitar_devolucion(self):
        if self.estado != 'activo':
            return False
        self.estado = 'dev_pendiente'
        db.session.commit()
        return True

    def confirmar_devolucion(self):
        if self.estado != 'dev_pendiente':
            return None
        producto = self.producto
        db.session.delete(self)
        db.session.flush()  # Ejecuta el delete antes de seguir

        # Si hay alguien en lista de espera, asignarle el producto
        if len(producto.en_espera) > 0:
            proximo_usuario = producto.en_espera[0]
            producto.en_espera.remove(proximo_usuario)
            nuevo_alquiler = Alquiler(
                usuario_id=proximo_usuario.id,
                producto_id=producto.id,
                estado='pendiente'
            )
            db.session.add(nuevo_alquiler)
            db.session.commit()
            return proximo_usuario
        else:
            producto.stock += 1
            producto.alquilado = False
            db.session.commit()
            return None


class Pelicula(ProductoAlquiler):
    formato = db.Column(db.String(50), nullable=True)             
    __mapper_args__ = {'polymorphic_identity': 'pelicula'}

    def obtener_especifico(self):
        return f"Formato: {self.formato}" if self.formato else "Sin formato"


class Juego(ProductoAlquiler):
    plataforma = db.Column(db.String(50), nullable=True)          
    __mapper_args__ = {'polymorphic_identity': 'juego'}

    def obtener_especifico(self):
        return f"Plataforma: {self.plataforma}" if self.plataforma else "Sin plataforma"


# =========================================================================
# CONTROLADOR GESTOR DE INVENTARIO
# =========================================================================
class GestorInventario:
    @staticmethod
    def agregar_producto(producto):
        db.session.add(producto)
        db.session.commit()

    @staticmethod
    def eliminar_producto(id_prod):
        prod = ProductoAlquiler.query.get(id_prod)
        if prod:
            prod.en_espera.clear()
            db.session.delete(prod)
            db.session.commit()
            return True
        return False

    @staticmethod
    def buscar_producto_por_id(id_prod):
        return ProductoAlquiler.query.get(id_prod)

    @staticmethod
    def listar_para_catalogo(clase_modelo, limite=None):
        query = clase_modelo.query.order_by(clase_modelo.contador_alquileres.desc(), clase_modelo.id.desc())
        if limite:
            query = query.limit(limite)
        return query.all()

    @staticmethod
    def calcular_ingresos_estimados():
        todos_los_productos = ProductoAlquiler.query.all()
        return sum(p.precio_alquiler * p.contador_alquileres for p in todos_los_productos)

    @staticmethod
    def solicitudes_pendientes():
        return Alquiler.query.filter_by(estado='pendiente').all()

    @staticmethod
    def devoluciones_pendientes():
        return Alquiler.query.filter_by(estado='dev_pendiente').all()

    @staticmethod
    def alquileres_activos():
        return Alquiler.query.filter_by(estado='activo').all()


# =========================================================================
# RUTAS PÚBLICAS Y DE CLIENTES
# =========================================================================

@app.route('/')
def inicio():
    peliculas = GestorInventario.listar_para_catalogo(Pelicula, limite=4)
    juegos = GestorInventario.listar_para_catalogo(Juego, limite=4)

    top_pelicula = peliculas[0] if peliculas else None
    top_juego = juegos[0] if juegos else None
    destacado = None
    if top_pelicula and top_juego:
        if top_pelicula.contador_alquileres >= top_juego.contador_alquileres:
            destacado = top_pelicula
        else:
            destacado = top_juego
    elif top_pelicula:
        destacado = top_pelicula
    elif top_juego:
        destacado = top_juego

    return render_template('inicio.html', 
                           peliculas=peliculas, 
                           juegos=juegos, 
                           destacado=destacado)

@app.route('/peliculas')
def ver_peliculas():
    peliculas = GestorInventario.listar_para_catalogo(Pelicula)
    return render_template('peliculas.html', peliculas=peliculas)

@app.route('/juegos')
def ver_juegos():
    juegos = GestorInventario.listar_para_catalogo(Juego)
    return render_template('juegos.html', juegos=juegos)

@app.route('/alquilar/<int:prod_id>')
def alquilar_item(prod_id):
    if 'usuario_id' not in session:
        flash("Debes iniciar sesión para alquilar o reservar.", "danger")
        return redirect(url_for('login'))

    usuario_actual = Usuario.buscar_por_id(session['usuario_id'])
    producto = GestorInventario.buscar_producto_por_id(prod_id)

    if not producto:
        flash("Producto no encontrado.", "danger")
        return redirect(request.referrer or url_for('inicio'))

    resultado = producto.solicitar_alquiler(usuario_actual)

    if resultado == "usuario_bloqueado":
        flash("Tu cuenta se encuentra SUSPENDIDA. Comunícate con soporte.", "danger")
    elif resultado == "ya_solicitado":
        flash("Ya tenés una solicitud pendiente o un alquiler activo para este producto.", "warning")
    elif resultado == "pendiente":
        flash("¡Solicitud enviada! El local la confirmará a la brevedad.", "info")
    elif resultado == "reservado":
        flash("Sin stock. ¡Te añadimos a la lista de espera!", "info")
    elif resultado == "ya_esperando":
        flash("Ya estás anotado en la lista de espera.", "warning")
        
    return redirect(request.referrer or url_for('inicio'))

@app.route('/devolver/<int:alquiler_id>')
def devolver_item(alquiler_id):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    usuario_actual = Usuario.buscar_por_id(session['usuario_id'])
    alquiler = Alquiler.query.get(alquiler_id)
    if alquiler and alquiler.usuario_id == usuario_actual.id and alquiler.solicitar_devolucion():
        flash(f"Devolución de '{alquiler.producto.titulo}' registrada. El local la confirmará cuando reciba el producto.", "info")
    else:
        flash("No se pudo registrar la devolución.", "danger")
    return redirect(url_for('mis_alquileres'))

@app.route('/cancelar-reserva/<int:prod_id>')
def cancelar_reserva(prod_id):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    usuario_actual = Usuario.buscar_por_id(session['usuario_id'])
    producto = GestorInventario.buscar_producto_por_id(prod_id)
    if producto and usuario_actual in producto.en_espera:
        producto.en_espera.remove(usuario_actual)
        db.session.commit()
        flash(f"Cancelaste tu reserva para '{producto.titulo}' correctamente.", "success")
    return redirect(request.referrer or url_for('inicio'))

@app.route('/mis-alquileres')
def mis_alquileres():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    usuario_actual = Usuario.buscar_por_id(session['usuario_id'])
    alquileres = Alquiler.query.filter_by(usuario_id=usuario_actual.id).filter(
        Alquiler.estado.in_(['pendiente', 'activo', 'dev_pendiente'])
    ).all()
    return render_template('mis_alquileres.html', 
                           alquileres=alquileres, 
                           reservas=usuario_actual.reservas_solicitadas)


# =========================================================================
# RUTAS EXCLUSIVAS DE ADMINISTRACIÓN
# =========================================================================

@app.route('/admin/dashboard', methods=['GET', 'POST'])
@requiere_nivel(5)
def dashboard():
    usuario_actual = Usuario.buscar_por_id(session.get('usuario_id'))
    
    if request.method == 'POST':
        tipo_f = request.form.get('tipo') 
        titulo = request.form.get('titulo')
        precio = float(request.form.get('precio'))
        stock = int(request.form.get('stock', 1))
        genero = request.form.get('genero')
        especifico_f = request.form.get('especifico') 
        
        file_imagen = request.files.get('imagen')
        if file_imagen and file_imagen.filename != '':
            nombre_imagen = secure_filename(file_imagen.filename)
            file_imagen.save(os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], nombre_imagen))
        else:
            nombre_imagen = request.form.get('imagen') or "default.jpg"

        if tipo_f == 'pelicula':
            nuevo = Pelicula(titulo=titulo, precio_alquiler=precio, stock=stock, genero=genero, imagen=nombre_imagen, formato=especifico_f)
        else:
            nuevo = Juego(titulo=titulo, precio_alquiler=precio, stock=stock, genero=genero, imagen=nombre_imagen, plataforma=especifico_f)

        GestorInventario.agregar_producto(nuevo)
        flash(f"¡{tipo_f.capitalize()} cargada correctamente!", "success")
        return redirect(url_for('dashboard'))

    usuarios_registrados = Usuario.query.filter(Usuario.rol == 'cliente').all()
    todos_los_productos = ProductoAlquiler.query.all()

    return render_template(
        'dashboard.html', 
        u_total=Usuario.query.count(), 
        p_total=Pelicula.query.count(), 
        j_total=Juego.query.count(), 
        ingresos=GestorInventario.calcular_ingresos_estimados(),
        usuarios=usuarios_registrados,
        productos=todos_los_productos,
        alquileres=GestorInventario.alquileres_activos(),
        solicitudes=GestorInventario.solicitudes_pendientes(),
        devoluciones=GestorInventario.devoluciones_pendientes(),
        es_admin=usuario_actual.es_admin()
    )

@app.route('/admin/nuevo_item', methods=['GET', 'POST'])
@requiere_nivel(10)
def nuevo_item():
    return redirect(url_for('dashboard'))

@app.route('/admin/usuario/bloquear/<int:user_id>')
@requiere_nivel(10)
def administrar_bloqueo(user_id):
    user = Usuario.buscar_por_id(user_id)
    if user:
        user.bloqueado = not user.bloqueado 
        db.session.commit()
        estado = "SANCIONADO" if user.bloqueado else "ACTIVADO"
        flash(f"Usuario {user.nombre} ha sido {estado}.", "success")
    return redirect(url_for('dashboard'))

@app.route('/admin/usuario/eliminar/<int:user_id>')
@requiere_nivel(10)
def administrar_eliminar_usuario(user_id):
    user = Usuario.buscar_por_id(user_id)
    if user:
        # Liberar stock de todos sus alquileres activos/pendientes
        for alquiler in user.mis_alquileres:
            if alquiler.estado in ('pendiente', 'activo', 'dev_pendiente'):
                alquiler.producto.stock += 1
                alquiler.producto.alquilado = False
        db.session.delete(user)
        db.session.commit()
        flash("Usuario eliminado del sistema correctamente.", "success")
    return redirect(url_for('dashboard'))

@app.route('/admin/usuario/editar/<int:user_id>', methods=['GET', 'POST'])
@requiere_nivel(10)
def administrar_editar_usuario(user_id):
    user = Usuario.buscar_por_id(user_id)
    if not user:
        flash("Usuario no encontrado.", "danger")
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        nuevo_email = request.form.get('email')
        existente = Usuario.query.filter_by(email=nuevo_email).first()
        if existente and existente.id != user_id:
            flash("Ese correo ya está en uso por otro usuario.", "danger")
            return redirect(url_for('administrar_editar_usuario', user_id=user_id))
        user.nombre = request.form.get('nombre')
        user.email  = nuevo_email
        nueva_pass  = request.form.get('password')
        if nueva_pass:
            user.password = nueva_pass
        db.session.commit()
        flash(f"Usuario '{user.nombre}' actualizado correctamente.", "success")
        return redirect(url_for('dashboard'))
    return render_template('editar_usuario.html', usuario=user)

@app.route('/admin/usuario/crear', methods=['GET', 'POST'])
@requiere_nivel(10)
def administrar_crear_usuario():
    if request.method == 'POST':
        nombre   = request.form.get('nombre')
        email    = request.form.get('email')
        password = request.form.get('password')
        rol      = request.form.get('rol', 'empleado')
        if Usuario.query.filter_by(email=email).first():
            flash("El correo ya está registrado.", "danger")
            return redirect(url_for('administrar_crear_usuario'))
        Usuario(nombre=nombre, email=email, password=password, rol=rol, activo=True).guardar()
        flash(f"Usuario '{nombre}' ({rol}) creado correctamente.", "success")
        return redirect(url_for('dashboard'))
    return render_template('crear_usuario_admin.html')

@app.route('/admin/producto/eliminar/<int:prod_id>')
@requiere_nivel(5)
def administrar_eliminar_producto(prod_id):
    if GestorInventario.eliminar_producto(prod_id):
        flash("Producto eliminado del inventario.", "success")
    return redirect(url_for('dashboard'))

@app.route('/admin/producto/editar-stock/<int:prod_id>', methods=['POST'])
@requiere_nivel(5)
def administrar_editar_stock(prod_id):
    producto = GestorInventario.buscar_producto_por_id(prod_id)
    if producto:
        nuevo_stock = int(request.form.get('nuevo_stock', 0))
        producto.stock = nuevo_stock
        # Asignar stock disponible a usuarios en lista de espera
        while producto.stock > 0 and len(producto.en_espera) > 0:
            proximo = producto.en_espera[0]
            producto.en_espera.remove(proximo)
            nuevo_alquiler = Alquiler(
                usuario_id=proximo.id,
                producto_id=producto.id,
                estado='pendiente'
            )
            db.session.add(nuevo_alquiler)
            producto.stock -= 1
            if producto.stock == 0:
                producto.alquilado = True
        db.session.commit()
        flash(f"Stock de '{producto.titulo}' actualizado con éxito.", "success")
    return redirect(url_for('dashboard'))

@app.route('/admin/producto/editar/<int:prod_id>', methods=['GET', 'POST'])
@requiere_nivel(5)
def administrar_editar_producto(prod_id):
    producto = GestorInventario.buscar_producto_por_id(prod_id)
    if not producto:
        flash("Producto no encontrado.", "danger")
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        producto.titulo          = request.form.get('titulo')
        producto.genero          = request.form.get('genero')
        producto.precio_alquiler = float(request.form.get('precio'))
        producto.stock           = int(request.form.get('stock', 0))
        especifico = request.form.get('especifico')
        if producto.tipo_producto == 'pelicula':
            producto.formato    = especifico
        else:
            producto.plataforma = especifico
        file_imagen = request.files.get('imagen')
        if file_imagen and file_imagen.filename != '':
            nombre_imagen = secure_filename(file_imagen.filename)
            file_imagen.save(os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], nombre_imagen))
            producto.imagen = nombre_imagen
        db.session.commit()
        flash(f"Producto '{producto.titulo}' actualizado correctamente.", "success")
        return redirect(url_for('dashboard'))
    return render_template('editar_producto.html', producto=producto)

@app.route('/admin/alquiler/confirmar/<int:alquiler_id>')
@requiere_nivel(5)
def confirmar_alquiler(alquiler_id):
    alquiler = Alquiler.query.get(alquiler_id)
    if alquiler and alquiler.confirmar():
        flash(f"Alquiler de '{alquiler.producto.titulo}' confirmado para {alquiler.usuario.nombre}.", "success")
    return redirect(url_for('dashboard'))

@app.route('/admin/alquiler/rechazar/<int:alquiler_id>')
@requiere_nivel(5)
def rechazar_alquiler(alquiler_id):
    alquiler = Alquiler.query.get(alquiler_id)
    if alquiler and alquiler.rechazar():
        flash(f"Solicitud de '{alquiler.producto.titulo}' rechazada. Stock repuesto.", "info")
    return redirect(url_for('dashboard'))

@app.route('/admin/devolucion/confirmar/<int:alquiler_id>')
@requiere_nivel(5)
def confirmar_devolucion(alquiler_id):
    alquiler = Alquiler.query.get(alquiler_id)
    if alquiler:
        titulo = alquiler.producto.titulo
        proximo = alquiler.confirmar_devolucion()
        if proximo:
            flash(f"Devolución confirmada. '{titulo}' asignado a {proximo.nombre} (lista de espera).", "info")
        else:
            flash(f"Devolución de '{titulo}' confirmada. Producto de vuelta en stock.", "success")
    return redirect(url_for('dashboard'))


# =========================================================================
# RUTAS DE AUTENTICACIÓN Y SESIÓN
# =========================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = Usuario.autenticar(request.form.get('email'), request.form.get('password'))
        if user:
            if not user.activo:
                flash("Tu cuenta aún no está verificada. Revisá tu correo.", "warning")
                return redirect(url_for('login'))
            session['usuario_id'] = user.id
            session['usuario_nombre'] = user.nombre
            session['usuario_rol'] = user.rol
            flash(f"¡Hola de nuevo, {user.nombre}!", "success")
            
            if user.es_staff():
                return redirect(url_for('dashboard'))
            return redirect(url_for('inicio'))
        flash("Credenciales incorrectas o inexistentes", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('inicio'))

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre, email, password = request.form.get('nombre'), request.form.get('email'), request.form.get('password')
        if Usuario.query.filter_by(email=email).first():
            flash("El correo ya está registrado.", "danger")
            return redirect(url_for('registro'))
        
        nuevo = Usuario(nombre=nombre, email=email, password=password, rol='cliente', activo=False)
        nuevo.guardar()

        try:
            token = ts.dumps(email, salt='activar-cuenta')
            link = url_for('confirmar_email', token=token, _external=True)
            msg = Message(subject="Verificá tu cuenta", recipients=[email])
            msg.body = f"Para activar tu cuenta, hacé click acá: {link}"
            mail.send(msg)
        except Exception as e:
            print(f"--- ERROR AL ENVIAR MAIL: {e} ---")

        flash(f"¡Cuenta creada! Te enviamos un mail a {email} para verificarla.", "success")
        return redirect(url_for('login'))
    return render_template('registro.html')

@app.route('/confirmar/<token>')
def confirmar_email(token):
    try:
        email = ts.loads(token, salt='activar-cuenta', max_age=86400)
        usuario = Usuario.query.filter_by(email=email).first()
        if usuario:
            usuario.activo = True
            db.session.commit()
            return "<h1>¡Cuenta verificada!</h1><p>Ya podés cerrar esta pestaña e iniciar sesión.</p>"
        return "Usuario no encontrado."
    except:
        return "<h1>El enlace es inválido o ya venció.</h1>"
    
@app.route('/recuperar-password', methods=['GET', 'POST'])
def recuperar_password():
    if request.method == 'POST':
        email = request.form['email']
        
        # Buscamos al usuario usando el ORM
        usuario = Usuario.query.filter_by(email=email).first()
        
        if usuario:
            # POO: Llamamos al método estático de la clase
            token = Usuario.generar_token_recupero(email)
            link = url_for('resetear_password', token=token, _external=True)
            
            msg = Message("Recuperación de contraseña", recipients=[email])
            msg.body = f"Hacé clic en el siguiente enlace para restablecer tu contraseña: {link}"
            mail.send(msg)
            
        flash("Si el correo existe, recibirás un mensaje en breve.")
        return redirect(url_for('login'))
        
    return render_template('recuperar.html')


@app.route('/resetear-password/<token>', methods=['GET', 'POST'])
def resetear_password(token):
    # POO: Usamos la clase para verificar el token que vino por la URL
    email = Usuario.verificar_token_recupero(token)
    if not email:
        flash("El token es inválido o ya expiró.")
        return redirect(url_for('vista_login'))
    
    if request.method == 'POST':
        nueva_password = request.form['password']
        
        usuario = Usuario.query.filter_by(email=email).first()
        if usuario:
            # POO: El objeto usuario ejecuta su propio método para cambiarse la clave
            usuario.resetear_password(nueva_password)
            flash("Contraseña actualizada con éxito.")
            return redirect(url_for('login'))
            
    return render_template('resetear.html', token=token)
    
# =========================================================================
# INICIALIZACIÓN
# =========================================================================
with app.app_context():
    db.create_all()  
    
    if not Usuario.query.filter_by(email="admin@alquiler.com").first():
        Usuario(nombre="Admin", email="admin@alquiler.com", password="123", rol="admin", activo=True).guardar()

if __name__ == '__main__':
    app.run(debug=True)
from flask import Flask, render_template, request, url_for, session, redirect, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.secret_key = 'mi_llave_secreta_super_segura'

# =========================================================================
# CONFIGURACIÓN DE LA BASE DE DATOS
# =========================================================================
db_path = os.path.join(os.path.dirname(__file__), 'alquileres.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

app.config['UPLOAD_FOLDER'] = os.path.join('static', 'img')

lista_espera = db.Table('lista_espera',
    db.Column('usuario_id', db.Integer, db.ForeignKey('usuarios.id'), primary_key=True),
    db.Column('producto_id', db.Integer, db.ForeignKey('productos_alquiler.id'), primary_key=True)
)

# =========================================================================
# MODELOS DE CLASES (POO)
# =========================================================================

class Usuario(db.Model):
    __tablename__ = 'usuarios'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    rol = db.Column(db.String(20), default='cliente') 
    bloqueado = db.Column(db.Boolean, default=False) # CONTROL DE SANCIONES

    alquileres = db.relationship('ProductoAlquiler', backref='usuario', lazy=True)
    reservas_solicitadas = db.relationship('ProductoAlquiler', secondary=lista_espera, backref=db.backref('en_espera', lazy=True))

    def guardar(self):
        db.session.add(self)
        db.session.commit()

    def es_staff(self):
        # Devuelve True si el usuario puede operar el panel (empleado o admin)
        return self.rol in ('empleado', 'admin')

    def es_admin(self):
        # Devuelve True solo para el rol con control total del sistema
        return self.rol == 'admin'

    @classmethod
    def buscar_por_id(cls, usuario_id):
        return cls.query.get(usuario_id)

    @classmethod
    def autenticar(cls, email_f, pass_f):
        return cls.query.filter_by(email=email_f, password=pass_f).first()


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

    # TRAZABILIDAD TEMPORAL Y PROPIEDAD
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    fecha_alquiler = db.Column(db.DateTime, nullable=True)
    fecha_vencimiento = db.Column(db.DateTime, nullable=True)

    # CICLO DE VIDA DEL ALQUILER
    # 'disponible' → libre en el local
    # 'pendiente'  → cliente solicitó, espera confirmación del local
    # 'activo'     → local confirmó, en manos del cliente
    # 'dev_pendiente' → cliente avisó que devolvió, espera confirmación física
    estado = db.Column(db.String(30), default='disponible')

    __mapper_args__ = {
        'polymorphic_on': tipo_producto,
        'polymorphic_identity': 'producto_generico'
    }

    def obtener_especifico(self):
        return "No aplica"

    def esta_vencido(self):
        if self.fecha_vencimiento and datetime.now() > self.fecha_vencimiento:
            return True
        return False

    def alquilar_a(self, usuario):
        # 1. Regla de negocio: Validar si el usuario está bloqueado
        if usuario.bloqueado:
            return "usuario_bloqueado"

        # 2. Alquiler directo con asignación de fechas (7 días de plazo fijo)
        if self.stock > 0:
            self.stock -= 1
            self.contador_alquileres += 1 
            self.usuario_id = usuario.id 
            self.fecha_alquiler = datetime.now()
            self.fecha_vencimiento = datetime.now() + timedelta(days=7)
            
            if self.stock == 0:
                self.alquilado = True                                             
            db.session.commit()
            return "alquilado"
        
        # 3. Lista de espera
        elif usuario not in self.en_espera:
            self.en_espera.append(usuario)
            db.session.commit()
            return "reservado"
        
        return "ya_esperando"

    def devolver_producto(self):
        # Si hay personas esperando, el sistema asigna el producto con un nuevo plazo de 7 días
        if len(self.en_espera) > 0:
            proximo_usuario = self.en_espera.pop(0)
            self.usuario_id = proximo_usuario.id
            self.fecha_alquiler = datetime.now()
            self.fecha_vencimiento = datetime.now() + timedelta(days=7)
            self.contador_alquileres += 1
            db.session.commit()
            return proximo_usuario
        
        # Devolución normal
        else:
            self.stock += 1
            self.alquilado = False                                                                    
            self.usuario_id = None 
            self.fecha_alquiler = None
            self.fecha_vencimiento = None
            db.session.commit()
            return None

    # ── NUEVO: Flujo de confirmación por el local ────────────────────────

    def solicitar_alquiler(self, usuario):
        # El cliente pide el producto → queda en 'pendiente' hasta que el local confirme
        if usuario.bloqueado:
            return "usuario_bloqueado"
        if self.stock > 0:
            self.stock -= 1
            self.usuario_id = usuario.id
            self.estado = 'pendiente'
            if self.stock == 0:
                self.alquilado = True
            db.session.commit()
            return "pendiente"
        # Sin stock → lista de espera (igual que antes)
        elif usuario not in self.en_espera:
            self.en_espera.append(usuario)
            db.session.commit()
            return "reservado"
        return "ya_esperando"

    def confirmar_alquiler(self):
        # El empleado/admin confirma → se activa el plazo de 7 días
        if self.estado != 'pendiente':
            return False
        self.estado = 'activo'
        self.fecha_alquiler = datetime.now()
        self.fecha_vencimiento = datetime.now() + timedelta(days=7)
        self.contador_alquileres += 1
        db.session.commit()
        return True

    def rechazar_alquiler(self):
        # El empleado/admin rechaza → el producto vuelve al stock disponible
        if self.estado != 'pendiente':
            return False
        self.stock += 1
        self.alquilado = False
        self.usuario_id = None
        self.estado = 'disponible'
        db.session.commit()
        return True

    def solicitar_devolucion(self, usuario):
        # El cliente avisa que devolvió → queda en 'dev_pendiente' hasta confirmación física
        if self.usuario_id != usuario.id or self.estado != 'activo':
            return False
        self.estado = 'dev_pendiente'
        db.session.commit()
        return True

    def confirmar_devolucion(self):
        # El empleado/admin confirma que el producto llegó físicamente al local
        if self.estado != 'dev_pendiente':
            return None
        # Si hay lista de espera, se asigna automáticamente al próximo (FIFO)
        if len(self.en_espera) > 0:
            proximo_usuario = self.en_espera.pop(0)
            self.usuario_id = proximo_usuario.id
            self.estado = 'pendiente'   # el próximo también pasa por confirmación
            db.session.commit()
            return proximo_usuario
        # Devolución normal: vuelve al stock
        self.stock += 1
        self.alquilado = False
        self.usuario_id = None
        self.fecha_alquiler = None
        self.fecha_vencimiento = None
        self.estado = 'disponible'
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
            # Si estaba alquilado por alguien, limpiamos la relación antes de borrar
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
    def procesar_alquiler(id_prod, usuario):
        producto = ProductoAlquiler.query.get(id_prod)
        if not producto:
            return "no_encontrado"
        
        # Delegamos la lógica de negocio pesada al producto (Experto en información)
        return producto.alquilar_a(usuario)

    @staticmethod
    def calcular_ingresos_estimados():
        # Traemos TODOS los productos del inventario
        todos_los_productos = ProductoAlquiler.query.all()
        
        # Multiplicamos el precio por la cantidad de veces que se alquiló cada uno
        return sum(p.precio_alquiler * p.contador_alquileres for p in todos_los_productos)

    @staticmethod
    def solicitudes_pendientes():
        # Alquileres que el cliente solicitó y esperan confirmación del local
        return ProductoAlquiler.query.filter_by(estado='pendiente').all()

    @staticmethod
    def devoluciones_pendientes():
        # Devoluciones avisadas por el cliente que esperan confirmación física
        return ProductoAlquiler.query.filter_by(estado='dev_pendiente').all()


# RUTAS PÚBLICAS Y DE CLIENTES


@app.route('/')
def inicio():
    peliculas = GestorInventario.listar_para_catalogo(Pelicula, limite=5)
    juegos = GestorInventario.listar_para_catalogo(Juego, limite=5)
    return render_template('inicio.html', peliculas=peliculas, juegos=juegos)

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

    # El cliente solicita → el producto queda pendiente de confirmación del local
    resultado = producto.solicitar_alquiler(usuario_actual)

    if resultado == "usuario_bloqueado":
        flash("Tu cuenta se encuentra SUSPENDIDA. Comunícate con soporte.", "danger")
    elif resultado == "pendiente":
        flash("¡Solicitud enviada! El local la confirmará a la brevedad.", "info")
    elif resultado == "reservado":
        flash("Sin stock. ¡Te añadimos a la lista de espera!", "info")
    elif resultado == "ya_esperando":
        flash("Ya estás anotado en la lista de espera.", "warning")
        
    return redirect(request.referrer or url_for('inicio'))

@app.route('/devolver/<int:prod_id>')
def devolver_item(prod_id):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    usuario_actual = Usuario.buscar_por_id(session['usuario_id'])
    producto = GestorInventario.buscar_producto_por_id(prod_id)
    if producto and producto.solicitar_devolucion(usuario_actual):
        flash(f"Devolución de '{producto.titulo}' registrada. El local la confirmará cuando reciba el producto.", "info")
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
    return render_template('mis_alquileres.html', alquileres=usuario_actual.alquileres, reservas=usuario_actual.reservas_solicitadas)


# RUTAS EXCLUSIVAS DE ADMINISTRACIÓN (SUPER PANEL)


@app.route('/admin/dashboard', methods=['GET', 'POST'])
def dashboard():
    # Acceso para empleados y admins
    usuario_actual = Usuario.buscar_por_id(session.get('usuario_id'))
    if not usuario_actual or not usuario_actual.es_staff():
        flash("Acceso denegado.", "danger")
        return redirect(url_for('inicio'))

    # PROCESAR EL ALTA DE PRODUCTOS NUEVOS (MÓDULO GESTIONAR PRODUCTOS)
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
            nombre_imagen = "default.jpg"

        if tipo_f == 'pelicula':
            nuevo = Pelicula(titulo=titulo, precio_alquiler=precio, stock=stock, genero=genero, imagen=nombre_imagen, formato=especifico_f)
        else:
            nuevo = Juego(titulo=titulo, precio_alquiler=precio, stock=stock, genero=genero, imagen=nombre_imagen, plataforma=especifico_f)

        GestorInventario.agregar_producto(nuevo)
        flash(f"¡{tipo_f.capitalize()} cargada correctamente!", "success")
        return redirect(url_for('dashboard'))

    # ENVIAR DATOS COMPLETOS A LAS 3 OPCIONES DEL PANEL
    usuarios_registrados = Usuario.query.filter(Usuario.rol == 'cliente').all()
    todos_los_productos = ProductoAlquiler.query.all()
    alquileres_activos = ProductoAlquiler.query.filter(ProductoAlquiler.estado == 'activo').all()

    return render_template(
        'dashboard.html', 
        u_total=Usuario.query.count(), 
        p_total=Pelicula.query.count(), 
        j_total=Juego.query.count(), 
        ingresos=GestorInventario.calcular_ingresos_estimados(),
        usuarios=usuarios_registrados,
        productos=todos_los_productos,
        alquileres=alquileres_activos,
        solicitudes=GestorInventario.solicitudes_pendientes(),
        devoluciones=GestorInventario.devoluciones_pendientes(),
        es_admin=usuario_actual.es_admin()
    )

@app.route('/admin/usuario/bloquear/<int:user_id>')
def administrar_bloqueo(user_id):
    usuario_actual = Usuario.buscar_por_id(session.get('usuario_id'))
    if not usuario_actual or not usuario_actual.es_admin(): return redirect(url_for('inicio'))
    user = Usuario.buscar_por_id(user_id)
    if user:
        user.bloqueado = not user.bloqueado # Invierte el booleano
        db.session.commit()
        estado = "SANCIONADO" if user.bloqueado else "ACTIVADO"
        flash(f"Usuario {user.nombre} ha sido {estado}.", "success")
    return redirect(url_for('dashboard'))

@app.route('/admin/usuario/eliminar/<int:user_id>')
def administrar_eliminar_usuario(user_id):
    usuario_actual = Usuario.buscar_por_id(session.get('usuario_id'))
    if not usuario_actual or not usuario_actual.es_admin(): return redirect(url_for('inicio'))
    user = Usuario.buscar_por_id(user_id)
    if user:
        # Liberamos los productos que tenía alquilados antes de borrarlo
        for p in user.alquileres:
            p.devolver_producto()
        db.session.delete(user)
        db.session.commit()
        flash("Usuario eliminado del sistema correctamente.", "success")
    return redirect(url_for('dashboard'))

@app.route('/admin/usuario/editar/<int:user_id>', methods=['GET', 'POST'])
def administrar_editar_usuario(user_id):
    usuario_actual = Usuario.buscar_por_id(session.get('usuario_id'))
    if not usuario_actual or not usuario_actual.es_admin(): return redirect(url_for('inicio'))
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
def administrar_crear_usuario():
    # Solo el admin puede crear empleados u otros admins
    usuario_actual = Usuario.buscar_por_id(session.get('usuario_id'))
    if not usuario_actual or not usuario_actual.es_admin(): return redirect(url_for('inicio'))
    if request.method == 'POST':
        nombre   = request.form.get('nombre')
        email    = request.form.get('email')
        password = request.form.get('password')
        rol      = request.form.get('rol', 'empleado')
        if Usuario.query.filter_by(email=email).first():
            flash("El correo ya está registrado.", "danger")
            return redirect(url_for('administrar_crear_usuario'))
        Usuario(nombre=nombre, email=email, password=password, rol=rol).guardar()
        flash(f"Usuario '{nombre}' ({rol}) creado correctamente.", "success")
        return redirect(url_for('dashboard'))
    return render_template('crear_usuario_admin.html')

@app.route('/admin/producto/eliminar/<int:prod_id>')
def administrar_eliminar_producto(prod_id):
    usuario_actual = Usuario.buscar_por_id(session.get('usuario_id'))
    if not usuario_actual or not usuario_actual.es_staff(): return redirect(url_for('inicio'))
    if GestorInventario.eliminar_producto(prod_id):
        flash("Producto eliminado del inventario.", "success")
    return redirect(url_for('dashboard'))

@app.route('/admin/producto/editar-stock/<int:prod_id>', methods=['POST'])
def administrar_editar_stock(prod_id):
    usuario_actual = Usuario.buscar_por_id(session.get('usuario_id'))
    if not usuario_actual or not usuario_actual.es_staff(): return redirect(url_for('inicio'))
    producto = GestorInventario.buscar_producto_por_id(prod_id)
    if producto:
        nuevo_stock = int(request.form.get('nuevo_stock', 0))
        producto.stock = nuevo_stock
        
        # Si sumamos stock y hay clientes esperando en la fila, los procesamos automáticamente (FIFO)
        while producto.stock > 0 and len(producto.en_espera) > 0:
            proximo = producto.en_espera.pop(0)
            producto.usuario_id = proximo.id
            producto.estado = 'pendiente'   # pasa por confirmación igual
            producto.stock -= 1
            if producto.stock == 0:
                producto.alquilado = True
                
        db.session.commit()
        flash(f"Stock de '{producto.titulo}' actualizado con éxito.", "success")
    return redirect(url_for('dashboard'))

@app.route('/admin/producto/editar/<int:prod_id>', methods=['GET', 'POST'])
def administrar_editar_producto(prod_id):
    usuario_actual = Usuario.buscar_por_id(session.get('usuario_id'))
    if not usuario_actual or not usuario_actual.es_staff(): return redirect(url_for('inicio'))
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

# Confirmación y rechazo de alquileres / devoluciones 

@app.route('/admin/alquiler/confirmar/<int:prod_id>')
def confirmar_alquiler(prod_id):
    usuario_actual = Usuario.buscar_por_id(session.get('usuario_id'))
    if not usuario_actual or not usuario_actual.es_staff(): return redirect(url_for('inicio'))
    producto = GestorInventario.buscar_producto_por_id(prod_id)
    if producto and producto.confirmar_alquiler():
        flash(f"Alquiler de '{producto.titulo}' confirmado para {producto.usuario.nombre}.", "success")
    return redirect(url_for('dashboard'))

@app.route('/admin/alquiler/rechazar/<int:prod_id>')
def rechazar_alquiler(prod_id):
    usuario_actual = Usuario.buscar_por_id(session.get('usuario_id'))
    if not usuario_actual or not usuario_actual.es_staff(): return redirect(url_for('inicio'))
    producto = GestorInventario.buscar_producto_por_id(prod_id)
    if producto and producto.rechazar_alquiler():
        flash(f"Solicitud de '{producto.titulo}' rechazada. Stock repuesto.", "info")
    return redirect(url_for('dashboard'))

@app.route('/admin/devolucion/confirmar/<int:prod_id>')
def confirmar_devolucion(prod_id):
    usuario_actual = Usuario.buscar_por_id(session.get('usuario_id'))
    if not usuario_actual or not usuario_actual.es_staff(): return redirect(url_for('inicio'))
    producto = GestorInventario.buscar_producto_por_id(prod_id)
    if producto:
        proximo = producto.confirmar_devolucion()
        if proximo:
            flash(f"Devolución confirmada. '{producto.titulo}' asignado a {proximo.nombre} (lista de espera).", "info")
        else:
            flash(f"Devolución de '{producto.titulo}' confirmada. Producto de vuelta en stock.", "success")
    return redirect(url_for('dashboard'))


# RUTAS DE AUTENTICACIÓN Y SESIÓN


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = Usuario.autenticar(request.form.get('email'), request.form.get('password'))
        if user:
            session['usuario_id'], session['usuario_nombre'], session['usuario_rol'] = user.id, user.nombre, user.rol
            flash(f"¡Hola de nuevo, {user.nombre}!", "success")
            # El staff va directo al panel, los clientes al catálogo
            if user.es_staff():
                return redirect(url_for('dashboard'))
            return redirect(url_for('inicio'))
        flash("Credenciales incorrectas", "danger")
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
        Usuario(nombre=nombre, email=email, password=password, rol='cliente').guardar()
        flash("¡Cuenta creada con éxito!", "success")
        return redirect(url_for('login'))
    return render_template('registro.html')

# CREACION DEL USUARIO ADMIN
with app.app_context():
    db.create_all()  
    if not Usuario.query.filter_by(email="admin@alquiler.com").first():
        Usuario(nombre="Admin", email="admin@alquiler.com", password="123", rol="admin").guardar()

    # Empleado de prueba para demostrar el flujo de confirmaciones
    if not Usuario.query.filter_by(email="empleado@alquiler.com").first():
        Usuario(nombre="Laura Empleada", email="empleado@alquiler.com", password="123", rol="empleado").guardar()

    # 2. Crear Usuarios Clientes de prueba si la base de datos está vacía
    if Usuario.query.filter_by(rol='cliente').count() == 0:
        u1 = Usuario(nombre="Carlos Gómez", email="carlos@gmail.com", password="123", rol="cliente", bloqueado=False)
        u2 = Usuario(nombre="Mariana López", email="mariana@gmail.com", password="123", rol="cliente", bloqueado=False)
        u3 = Usuario(nombre="Esteban Quito", email="esteban@gmail.com", password="123", rol="cliente", bloqueado=False)
        u1.guardar()
        u2.guardar()
        u3.guardar()

        # 3. Crear Catálogo de Películas de muestra
        p1 = Pelicula(titulo="Inception (El Origen)", genero="Ciencia Ficción", precio_alquiler=350.00, stock=2, imagen="default.jpg", formato="BluRay-4K", contador_alquileres=15)
        p2 = Pelicula(titulo="El Padrino", genero="Drama / Crimen", precio_alquiler=300.00, stock=1, imagen="default.jpg", formato="DVD", contador_alquileres=40)
        
        # Esta peli inicia sin stock físico para probar las RESERVAS (Lista de espera)
        p3 = Pelicula(titulo="Avatar: El Camino del Agua", genero="Acción / Sci-Fi", precio_alquiler=500.00, stock=0, alquilado=True, imagen="default.jpg", formato="BluRay-3D", contador_alquileres=8)
        
        # Película especial: Se la asignamos directamente a Carlos simulando que la alquiló HACE 10 DÍAS (Ya venció el plazo de 7)
        fecha_hace_10_dias = datetime.now() - timedelta(days=10)
        fecha_vencimiento_vieja = fecha_hace_10_dias + timedelta(days=7)
        p4 = Pelicula(titulo="Batman: El Caballero de la Noche", genero="Acción", precio_alquiler=400.00, stock=0, alquilado=True, imagen="default.jpg", formato="BluRay-4K", usuario_id=u1.id, fecha_alquiler=fecha_hace_10_dias, fecha_vencimiento=fecha_vencimiento_vieja, contador_alquileres=52, estado='activo')

        # 4. Crear Catálogo de Videojuegos de muestra
        j1 = Juego(titulo="The Legend of Zelda: Tears of the Kingdom", genero="Aventura", precio_alquiler=800.00, stock=3, imagen="default.jpg", plataforma="Nintendo Switch", contador_alquileres=25)
        
        # Juego especial: Se lo asignamos a Mariana alquilado HOY (Está en término sin vencer)
        j2 = Juego(titulo="GTA V", genero="Acción / Mundo Abierto", precio_alquiler=450.00, stock=0, alquilado=True, imagen="default.jpg", plataforma="PS5", usuario_id=u2.id, fecha_alquiler=datetime.now(), fecha_vencimiento=datetime.now() + timedelta(days=7), contador_alquileres=90, estado='activo')
        
        # Juego sin stock — Carlos tiene una solicitud pendiente para demostrar el flujo de confirmación
        j3 = Juego(titulo="Elden Ring", genero="Action RPG", precio_alquiler=700.00, stock=0, alquilado=True, imagen="default.jpg", plataforma="PC / Steam", contador_alquileres=14, usuario_id=u1.id, estado='pendiente')

        # Guardamos todos los productos en la base de datos
        db.session.add_all([p1, p2, p3, p4, j1, j2, j3])
        db.session.commit()

        # 5. Forzar una fila de espera artificial para probar el backend
        # Hacemos que Esteban Quito ya esté haciendo fila esperando "Avatar"
        p3.en_espera.append(u3)
        db.session.commit()

        print("¡Base de datos inicializada con éxito con usuarios, catálogos y alquileres de prueba!")

if __name__ == '__main__':
    app.run(debug=True)
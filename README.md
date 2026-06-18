# 🎬🎮 Sistema de Gestión de Alquiler de Peliculas y Juegos

## 🚀 Objetivo del Proyecto
Este proyecto es una aplicación web desarrollada mediante **Flask** con el fin de desarrollar un sistema de software orientado a objetos que automatice la administración, alquiler y devolución de un catálogo de productos, brindandole a los administradores herramientas de  control de usuarios, y a los clientes un sistema de reservas eficiente.

## 🛠️ Componentes y Tecnologías
* **Backend:** Python 3.x con el microframework **Flask**.
* **Base de Datos:** SQLite. 
* **Frontend:** Plantillas dinámicas (HTML/CSS) 

## 📦 Estructura del Proyecto
```text
├── static/             # Archivos estáticos (CSS, imágenes)
├── templates/          # Plantillas HTML renderizadas por Flask
├── alquileres.db       # Base de datos SQLite del sistema
├── app.py              # Servidor principal y rutas de Flask
├── README.md           # Documentación del proyecto
└── requirements.txt    # Dependencias y librerías del proyecto
```



## 🗺️ Diagrama de Clases (UML)


```mermaid
classDiagram

    class Usuario {
        -id: Integer
        -nombre: String
        -email: String
        -password: String
        -rol: String
        -bloqueado: Boolean
        -activo: Boolean
        +guardar() void
        +es_staff() Boolean
        +es_admin() Boolean
        +buscar_por_id(usuario_id: Integer) Usuario$
        +autenticar(email_f: String, pass_f: String) Usuario$
    }

    class ProductoAlquiler {
        -id: Integer
        -titulo: String
        -genero: String
        -alquilado: Boolean
        -precio_alquiler: Float
        -stock: Integer
        -imagen: String
        -contador_alquileres: Integer
        -tipo_producto: String
        -usuario_id: Integer
        -fecha_alquiler: DateTime
        -fecha_vencimiento: DateTime
        -estado: String
        -precio: Float
        +obtener_especifico() String
        +esta_vencido() Boolean
        +alquilar_a(usuario: Usuario) String
        +devolver_producto() Usuario
        +solicitar_alquiler(usuario: Usuario) String
        +confirmar_alquiler() Boolean
        +rechazar_alquiler() Boolean
        +solicitar_devolucion(usuario: Usuario) Boolean
        +confirmar_devolucion() Usuario
    }

    class GestorInventario {
        +agregar_producto(producto: ProductoAlquiler) void
        +eliminar_producto(id_prod: Integer) Boolean
        +buscar_producto_por_id(id_prod: Integer) ProductoAlquiler
        +listar_para_catalogo(clase_modelo: Type, limite: Integer) List~ProductoAlquiler~$
        +procesar_alquiler(id_prod: Integer, usuario: Usuario) String
        +calcular_ingresos_estimados() Float
        +solicitudes_pendientes() List~ProductoAlquiler~$
        +devoluciones_pendientes() List~ProductoAlquiler~$
    }

    class Juego {
        -plataforma: String
        +obtener_especifico() String
    }

    class Pelicula {
        -formato: String
        +obtener_especifico() String
    }

    %% Relaciones
    Usuario "1" --> "0..*" ProductoAlquiler : alquila / posee

    GestorInventario ..> ProductoAlquiler : gestiona

    ProductoAlquiler <|-- Juego
    ProductoAlquiler <|-- Pelicula
```
## 🤝 Relaciones entre Clases

| Clase Origen | Relación | Clase Destino | Descripción |
|-------------|-----------|---------------|-------------|
| Usuario | Asociación (1 → 0..*) | ProductoAlquiler | Un usuario puede alquilar 0 o varios productos. |
| GestorInventario | Dependencia | ProductoAlquiler | Gestiona altas, bajas, búsquedas y alquileres de productos. |
| Juego | Herencia | ProductoAlquiler | Juego es un tipo específico de producto de alquiler. |
| Pelicula | Herencia | ProductoAlquiler | Película es un tipo específico de producto de alquiler. |


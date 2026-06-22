# Payment Hunter Pro

Herramienta de búsqueda para identificar formularios de pago reales en tiendas online.

## Características

- Búsqueda de pasarelas de pago (Adyen, Stripe, PayPal, Mercado Pago, Openpay, Authorize.net)
- Soporte para proxies rotativos
- Modo stealth anti-detección
- Filtros por país y tipo de sitio
- Dorks personalizados
- Exportación de resultados (CSV/Excel)

## Requisitos

```
pip install -r requirements.txt
python -m playwright install
```

## Uso

```bash
python payment_hunter_pro.py
```

## Nota

El archivo .spec está incluido para generar ejecutables con PyInstaller.

## Tests

Se agregaron pruebas unitarias para las partes aisladas y testeables (`PaymentDetector`, `SearchRunner`, `SearchResult`).

### Instalar dependencias de desarrollo

```bash
pip install -r requirements.txt
# (incluye pytest)
```

### Ejecutar los tests

```bash
# Con pytest (recomendado)
pytest

# O con unittest (sin dependencias extra)
python -m unittest discover -s tests
```

Los tests usan mocks pesados de playwright y ddgs para no requerir navegador ni conexión a internet durante la ejecución.

## Mejoras recientes implementadas

- Estructura modular limpia (models / detector / runner / ui)
- Reutilización del navegador (gran mejora de velocidad)
- UI de resultados con **ttk.Treeview** (mucho mejor que frames dinámicos)
- **Detección más inteligente** usando `page.query_selector` + score de confianza (0-100)
- Export más rico (incluye country, confidence_score, dork)
- Botón "Test Proxies"
- Selector de motor de búsqueda (preparado para expansión)
- Logging real + eliminación de código muerto

**Nota sobre asíncrono**: El soporte completo con Playwright Async + paralelismo está preparado para implementación futura (requiere reescritura del runner con asyncio).
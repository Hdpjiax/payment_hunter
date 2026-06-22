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
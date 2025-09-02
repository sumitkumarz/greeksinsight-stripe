# Stripe Membership Flask API

This project scaffolds a Flask API backend for a membership-based system with Stripe integration and Swagger documentation.

## Structure
- `app/`
  - `models/` (ORM models)
  - `routes/` (API endpoints)
  - `services/` (business logic, Stripe integration)
  - `config.py` (configuration)
  - `__init__.py` (app factory)
- `requirements.txt`
- `run.py` (entry point)
- `README.md`

## Features
- User registration/authentication
- Membership plan management
- Stripe customer/subscription management
- Webhook handling
- Swagger UI for API docs

## Setup
1. Install dependencies: `pip install -r requirements.txt`
2. Run the app: `python run.py`
3. Access Swagger UI at `/docs`

---
This README will be updated as features are implemented.

---
title: FinGuard — Real-Time Fraud Detection
emoji: 🛡️
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: true
short_description: Kafka streaming, XGBoost + SHAP, LLM risk-analyst agent
---

# FinGuard — Real-Time Fraud Detection & AI Risk Analyst

Live demo of [FinGuard](https://github.com/BGVRkReddy18/finguard). Sign in with a demo account:
**analyst / finguard123** or **manager / finguard123**.

Card transactions stream through Kafka, are scored in milliseconds by an XGBoost model with SHAP
explanations, and flagged cases are investigated by an LLM agent. Source code, architecture,
benchmarks and the multi-service production setup are on GitHub.

This Space runs the whole platform (Postgres, Redis, Kafka, Django, two FastAPI services, Next.js)
in one container. Demo data is simulated and resets when the Space restarts.

# 👋 Привет, я Андрей — Data Engineer

> Строю надёжные пайплайны данных: от сбора до бизнес-инсайтов.  
> Фокус: **DE/MLOps**, **lakehouse-архитектуры**, **real-time аналитика**.

<div class="grid cards" markdown>

-   :material-speedometer: **7+ проектов**  
    От прототипов до production-ready решений

-   :material-memory: **15+ технологий**  
    ClickHouse, Kafka, Iceberg, MinIO, Trino, Airflow, Docker

-   :material-domain: **3+ домена**  
    1С-экосистема, HR-tech (HH API), логистика и финансы

</div>

## 🗺️ Экосистема проектов

```mermaid
graph LR
    A[1c_tj_logs] --> B[ClickHouse]
    B --> C[lakehouse-local]
    B --> D[kafka_pipeline]
    A --> E[observability]
    
    style A fill:#FFA07A,stroke:#333
    style B fill:#4ECDC4,stroke:#333
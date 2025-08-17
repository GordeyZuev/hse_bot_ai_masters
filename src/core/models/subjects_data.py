"""
Начальные данные дисциплин для загрузки в базу данных
"""

# Дисциплины 1 курса
FIRST_YEAR_SUBJECTS = [
    {"name": "Python для анализа данных", "start_module": 1, "end_module": 1},
    {"name": "SQL", "start_module": 1, "end_module": 1},
    {"name": "Инструменты разработки", "start_module": 1, "end_module": 2},
    {"name": "Математика для анализа данных", "start_module": 1, "end_module": 2},
    {"name": "Анализ временных рядов", "start_module": 2, "end_module": 3},
    {"name": "Машинное обучение (ML)", "start_module": 2, "end_module": 3},
    {"name": "Прикладной Python", "start_module": 2, "end_module": 3},
    {"name": "Промышленная разработка", "start_module": 3, "end_module": 4},
    {"name": "Прикладная статистика для анализа данных", "start_module": 3, "end_module": 4},
    {"name": "Рекомендательные Системы", "start_module": 3, "end_module": 4},
    {"name": "Алгоритмы и Структуры Данных", "start_module": 4, "end_module": 4},
    {"name": "Глубинное обучение", "start_module": 4, "end_module": 4}
]

# Дисциплины 2 курса
SECOND_YEAR_SUBJECTS = [
    {"name": "BigData", "start_module": 5, "end_module": 6},
    {"name": "Введение в MLOps", "start_module": 5, "end_module": 5},
    {"name": "Генеративные модели", "start_module": 5, "end_module": 6},
    {"name": "Дополнительные главы ML", "start_module": 5, "end_module": 5},
    {"name": "ML System Design", "start_module": 5, "end_module": 5},
    {"name": "NLP - 1", "start_module": 5, "end_module": 5},
    {"name": "Введение в DE", "start_module": 6, "end_module": 6},
    {"name": "Векторный поиск", "start_module": 6, "end_module": 6},
    {"name": "DL для звука", "start_module": 6, "end_module": 7},
    {"name": "Интеллектуальный акустический мониторинг", "start_module": 6, "end_module": 6},
    {"name": "MLOps", "start_module": 6, "end_module": 6},
    {"name": "Мультимодальные нейросети", "start_module": 6, "end_module": 6},
    {"name": "NLP - 2", "start_module": 6, "end_module": 6},
    {"name": "Al Case Study (LLM Project)", "start_module": 7, "end_module": 7},
    {"name": "ГО на графах", "start_module": 7, "end_module": 7},
    {"name": "Компьютерное зрение", "start_module": 7, "end_module": 7},
    {"name": "НИС «Современное Машинное Обучение»", "start_module": 7, "end_module": 7},
    {"name": "Обучение с подкреплением", "start_module": 7, "end_module": 7},
    {"name": "Подготовка к собеседованиям", "start_module": 7, "end_module": 7},
    {"name": "Распределенные системы", "start_module": 7, "end_module": 7},
    {"name": "Факультатив BigData", "start_module": 7, "end_module": 7},
    {"name": "Факультатив LLM", "start_module": 7, "end_module": 7},
    {"name": "Валидация ИИ моделей", "start_module": 7, "end_module": 7},
    {"name": "Факультатив 3D CV", "start_module": 8, "end_module": 8}
]

# Объединенный список всех дисциплин для загрузки в БД
ALL_SUBJECTS = [
    # 1 курс
    *[{"name": subject["name"], "year": 1, "start_module": subject["start_module"], "end_module": subject["end_module"]} 
      for subject in FIRST_YEAR_SUBJECTS],
    # 2 курс  
    *[{"name": subject["name"], "year": 2, "start_module": subject["start_module"], "end_module": subject["end_module"]} 
      for subject in SECOND_YEAR_SUBJECTS],
]
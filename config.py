import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
USTAZ_BOT_TOKEN = os.getenv("USTAZ_BOT_TOKEN", "")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# OpenAI ChatGPT
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Paths
DATABASE_PATH = os.getenv("DATABASE_PATH", "./database/bot.db")
CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")
LOG_PATH = os.getenv("LOG_PATH", "./logs/bot.log")
KNOWLEDGE_DIR = os.getenv("KNOWLEDGE_DIR", "./knowledge")

# Cache (ChromaDB используется только как кэш для ИИ-ответов)
CACHE_THRESHOLD = float(os.getenv("CACHE_THRESHOLD", "0.90"))
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")

# Legacy (для совместимости)
SIMILARITY_THRESHOLD = CACHE_THRESHOLD

# Subscription
FREE_ANSWERS_LIMIT = int(os.getenv("FREE_ANSWERS_LIMIT", "5"))
WARNING_AT = int(os.getenv("WARNING_AT", "3"))
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "5"))

# Conversation History
CONVERSATION_HISTORY_LIMIT = int(os.getenv("CONVERSATION_HISTORY_LIMIT", "50"))

# Ustaz Consultations
USTAZ_MONTHLY_LIMIT = int(os.getenv("USTAZ_MONTHLY_LIMIT", "5"))

# Web Admin Panel (Basic Auth)
WEB_ADMIN_USER = os.getenv("WEB_ADMIN_USER", "admin")
WEB_ADMIN_PASSWORD = os.getenv("WEB_ADMIN_PASSWORD", "")

# Domain
DOMAIN = os.getenv("DOMAIN", "")

SUBSCRIPTION_PLANS = {
    "monthly": {"price": 990, "currency": "KZT", "days": 30},
    "yearly": {"price": 9900, "currency": "KZT", "days": 365},
}

# Messages
MSG_WELCOME = (
    "Ассалаумағалейкум! Мен — Рамазан айына қатысты сұрақтарға жауап беретін ИИ бот-көмекшімін.\n\n"
    "Маған ораза, зекет, садақа, тарауих, пітір және т.б. тақырыптар бойынша сұрақ қойыңыз.\n"
    "Мен қазақ және орыс тілдерін (кириллица және латиница) түсінемін.\n\n"
    "Алғашқы 5 жауап — тегін!\n\n"
    "Командалар:\n"
    "/help — анықтама\n"
    "/stats — сіздің статистикаңыз"
)

MSG_HELP = (
    "Сұрағыңызды жазып жіберіңіз, мен базадан жауап іздеймін.\n\n"
    "Мен қазақ тілін (кириллица және латиница) және орыс тілін түсінемін. "
    "Қате жазсаңыз да түсінемін.\n\n"
    "Тақырыптар: ораза, ниет, сәресі, ауызашар, тарауих, қадір түні, "
    "зекет, пітір садақа, иғтикаф және т.б.\n\n"
    "Командалар:\n"
    "/start — бастау\n"
    "/help — анықтама\n"
    "/stats — статистика (қанша жауап пайдаланылды, жазылым)\n"
    "/clear — диалог тарихын тазалау"
)

MSG_NOT_FOUND = "Кешіріңіз, сіздің сұрағыңызға жауап таба алмадым. Бұл тақырып базамызда жоқ болуы мүмкін. Сұрағыңызды басқаша қойып көріңіз."

MSG_AI_ERROR = "Кешіріңіз, ИИ сервисінде уақытша қате орын алды. Сәл күтіп, қайталап көріңіз."

MSG_LIMIT_REACHED = (
    "Сіз {limit} тегін жауаптың барлығын пайдаландыңыз.\n\n"
    "Жалғастыру үшін жазылымды рәсімдеңіз:"
)

MSG_WARNING = "Назар аударыңыз! Сізде {limit} тегін жауаптан {remaining} қалды."

MSG_NON_TEXT = "Мен тек мәтіндік хабарламаларды қабылдаймын. Сұрағыңызды мәтінмен жазыңыз."

MSG_RATE_LIMIT = "Сұраныстар тым көп. Сәл күтіп, қайта көріңіз."

MSG_SUBSCRIPTION_ACTIVE = "Жазылым {expires_at} дейін белсендірілді. Жақсы пайдалану тілейміз!"

MSG_ADMIN_ONLY = "Бұл команда тек әкімшілерге қол жетімді."

MSG_HISTORY_CLEARED = "Диалог тарихы тазаланды. Жаңа сұхбат бастауға болады."

# Ustaz consultation messages
MSG_ASK_USTAZ_BUTTON = "Устазға сұрақ қою"
MSG_ASK_USTAZ_CONFIRM = (
    "Сіз устазға сұрақ қойғыңыз келе ме?\n\n"
    "Ай сайын {limit} рет сұрақ қоюға болады.\n"
    "Сізде {remaining} мүмкіндік қалды.\n\n"
    "Сұрағыңызды жазыңыз:"
)
MSG_ASK_USTAZ_LIMIT = (
    "Кешіріңіз, сіз бұл айда устазға {limit} рет сұрақ қойдыңыз.\n"
    "Келесі айда қайта сұрай аласыз."
)
MSG_ASK_USTAZ_SENT = (
    "Сұрағыңыз устазға жіберілді! Жауап келгенде хабарлаймыз."
)
MSG_ASK_USTAZ_SUBSCRIBERS_ONLY = (
    "Устазға сұрақ қою тек жазылымшыларға қол жетімді.\n"
    "Жазылым рәсімдеу үшін /start командасын жіберіңіз."
)
MSG_CONSULTATION_ANSWER = (
    "Устаздан жауап келді!\n\n"
    "Сіздің сұрағыңыз:\n{question}\n\n"
    "Устаздың жауабы:\n{answer}"
)
MSG_ASK_USTAZ_WRITE_QUESTION = "Устазға сұрағыңызды жазыңыз:"
MSG_ASK_USTAZ_CANCEL = "Сұрақ жіберу тоқтатылды."

# Ustaz bot messages
MSG_USTAZ_WELCOME = (
    "Ассалаумағалейкум, устаз!\n\n"
    "Бұл — консультация панелі. Пайдаланушылар сұрақтарына жауап беруге болады.\n\n"
    "Командалар:\n"
    "/queue — кезекті көру\n"
    "/mystats — менің статистикам\n"
)
MSG_USTAZ_NOT_REGISTERED = "Сіз устаз ретінде тіркелмегенсіз. Әкімшіге хабарласыңыз."
MSG_USTAZ_QUEUE_EMPTY = "Кезекте сұрақтар жоқ."
MSG_USTAZ_QUESTION_TAKEN = "Сұрақ қабылданды. Жауабыңызды жазыңыз:"
MSG_USTAZ_QUESTION_ALREADY_TAKEN = "Бұл сұрақты басқа устаз алды."
MSG_USTAZ_ANSWER_SENT = "Жауабыңыз пайдаланушыға жіберілді!"
MSG_USTAZ_HAS_ACTIVE = "Сізде аяқталмаған сұрақ бар. Алдымен оған жауап беріңіз."
MSG_USTAZ_NEW_QUESTION = (
    "Жаңа сұрақ келді!\n\n"
    "Пайдаланушы: {user_name}\n"
    "Сұрақ: {question}\n\n"
    "/queue — кезекті көру"
)

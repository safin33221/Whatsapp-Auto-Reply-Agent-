
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")

if not api_key:
    raise ValueError("OPENROUTER_API_KEY পাওয়া যায়নি!")

llm = ChatOpenAI(
    model="openrouter/free",
    api_key=api_key,
    base_url="https://openrouter.ai/api/v1",
    temperature=0.3,
    timeout=30,
    max_retries=1,
)

try:
    response = llm.invoke(
        "Reply in Bangla: I am busy right now."
    )
    print("AI response:", response.content)

except Exception as error:
    print("AI API Error:", repr(error))

import asyncio
from unittest.mock import AsyncMock, MagicMock
from telegram import Update, CallbackQuery, User
from main import button_click

async def test():
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 1170387402  # Developer ID

    query = AsyncMock(spec=CallbackQuery)
    query.data = "pay_qris"
    update.callback_query = query
    update.message = MagicMock()

    context = MagicMock()
    context.user_data = {}

    print("Calling button_click...")
    try:
        await button_click(update, context)
        print("Success! query.answer was called with:", query.answer.call_args)
        print("query.edit_message_text was called with:", query.edit_message_text.call_args)
    except Exception as e:
        print("Exception occurred:", type(e).__name__, str(e))
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())

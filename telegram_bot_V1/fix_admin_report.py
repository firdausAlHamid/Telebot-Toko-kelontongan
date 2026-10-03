import re

with open("admin_report_handlers.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update imports
content = content.replace("from auth import require", "from auth import require, get_tenant_id, can")

# 2. Add tenant_id to summary calls
content = re.sub(
    r"summary = get_daily_summary\((.*?)\)",
    r"summary = get_daily_summary(\1, tenant_id=tenant_id)",
    content
)
content = re.sub(
    r"summary = get_period_summary\((.*?)\)",
    r"summary = get_period_summary(\1, tenant_id=tenant_id)",
    content
)
content = re.sub(
    r"top = get_top_products\((.*?)\)",
    r"top = get_top_products(\1, tenant_id=tenant_id)",
    content
)

# 3. Add tenant_id = get_tenant_id(update.effective_user.id) at the start of handle_report_menu
handle_report_match = re.search(r"async def handle_report_menu\(update: Update, context: ContextTypes.DEFAULT_TYPE\):\n(.*?)(    query = update.callback_query)", content, re.DOTALL)
if handle_report_match:
    original = handle_report_match.group(0)
    replacement = original.replace("    query = update.callback_query", "    tenant_id = get_tenant_id(update.effective_user.id)\n    query = update.callback_query")
    content = content.replace(original, replacement)

# 4. Fix riwayat_command
riwayat_old = """async def riwayat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    \"\"\"Show last 5 transactions for the current user (or all for admin).\"\"\"
    user_id = update.effective_user.id
    # Owner sees all transactions; kasir sees only their own
    if is_owner(user_id):
        transactions, total = get_transaction_history(limit=10)
        title = f"📜 *Riwayat Transaksi* (semua — {total} total)"
    else:
        transactions, total = get_transaction_history(user_id=user_id, limit=5)
        title = f"📜 *Riwayat Transaksi Kamu* ({total} total)\""""
riwayat_new = """@require("history:view_self")
async def riwayat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    \"\"\"Show last 5 transactions for the current user (or all for admin).\"\"\"
    user_id = update.effective_user.id
    tenant_id = get_tenant_id(user_id)
    # Owner sees all transactions; kasir sees only their own
    if can(user_id, "history:view_tenant"):
        transactions, total = get_transaction_history(limit=10, tenant_id=tenant_id)
        title = f"📜 *Riwayat Transaksi* (semua — {total} total)"
    else:
        transactions, total = get_transaction_history(user_id=user_id, limit=5, tenant_id=tenant_id)
        title = f"📜 *Riwayat Transaksi Kamu* ({total} total)\""""
content = content.replace(riwayat_old, riwayat_new)

# 5. Add tenant_id to get_transaction_history in _show_void_list
content = re.sub(
    r"transactions, total = get_transaction_history\(status=\"completed\", limit=15\)",
    r"tenant_id = get_tenant_id(update.effective_user.id)\n    transactions, total = get_transaction_history(status=\"completed\", limit=15, tenant_id=tenant_id)",
    content
)

# 6. Add tenant_id to void_transaction
content = re.sub(
    r"success, msg = void_transaction\(trx_id, reason=reason\)",
    r"tenant_id = get_tenant_id(update.effective_user.id)\n    success, msg = void_transaction(trx_id, reason=reason, tenant_id=tenant_id)",
    content
)

with open("admin_report_handlers.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Updated admin_report_handlers.py")

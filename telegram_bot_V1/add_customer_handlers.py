import re

with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

customer_handlers = """
    # --- Customer Catalog Handlers ---
    if data == "customer_katalog":
        await query.answer()
        tenant_id = get_tenant_id(user_id)
        reply_markup = build_categories_keyboard(tenant_id=tenant_id, is_customer=True)
        await query.edit_message_text(
            "🛒 *Katalog Produk*\n\nPilih kategori produk di bawah ini untuk melihat daftar barang:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return

    if data.startswith("ccat_"):
        await query.answer()
        tenant_id = get_tenant_id(user_id)
        category_prefix = data.split("_")[1]
        reply_markup, full_cat_name = build_products_keyboard(category_prefix, page=1, tenant_id=tenant_id, is_customer=True)
        await query.edit_message_text(
            f"🛒 *Kategori: {full_cat_name}*",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return

    if data.startswith("cpage_"):
        await query.answer()
        tenant_id = get_tenant_id(user_id)
        parts = data.split("_")
        category_prefix = parts[1]
        page = int(parts[2])
        reply_markup, full_cat_name = build_products_keyboard(category_prefix, page=page, tenant_id=tenant_id, is_customer=True)
        await query.edit_message_text(
            f"🛒 *Kategori: {full_cat_name}* (Page {page})",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return

    if data == "cback_to_cat":
        await query.answer()
        tenant_id = get_tenant_id(user_id)
        reply_markup = build_categories_keyboard(tenant_id=tenant_id, is_customer=True)
        await query.edit_message_text(
            "🛒 *Katalog Produk*\n\nPilih kategori produk di bawah ini untuk melihat daftar barang:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return

    if data.startswith("cprod_"):
        await query.answer()
        return

    if data == "back_to_main":
        await show_main_menu(update, context)
        return

    # --- End Customer Catalog Handlers ---
"""

# Insert right after `if data == "noop": ... return`
match = re.search(r'if data == "noop":\n        await query\.answer\(\)\n        return\n', content)
if match:
    insert_pos = match.end()
    content = content[:insert_pos] + customer_handlers + content[insert_pos:]
    with open("main.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("Customer handlers added successfully.")
else:
    print("Could not find insertion point!")

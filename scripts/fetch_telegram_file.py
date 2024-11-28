import asyncio
from telethon import TelegramClient

api_id = '2040'
api_hash = 'b18441a1ff607e10a989891a5462e627'
session_name = 'chat_name'
group_id = 1604486631
topic_id = 752

async def fetch_latest_file(client, group_id, topic_id):
    try:
        group_entity = await client.get_entity(group_id)
        messages = await client.get_messages(
            group_entity,
            limit=80,
            reply_to=topic_id
        )
        file_messages = [msg for msg in messages if msg.file]
        if not file_messages:
            print("未找到包含文件的消息。")
            return
        latest_message = max(file_messages, key=lambda msg: msg.date)
        file_name = latest_message.file.name

        # 使用字符串操作提取括号内的内容
        if '(' in file_name and ')' in file_name:
            start = file_name.index('(') + 1
            end = file_name.index(')')
            number_in_parentheses = file_name[start:end]
            print(f"{number_in_parentheses}")
        else:
            print("未找到括号中的内容。")
    except Exception as e:
        print(f"获取文件失败: {e}")

async def main():
    client = TelegramClient(session_name, api_id, api_hash)
    await client.start()
    await fetch_latest_file(client, group_id, topic_id)
    await client.disconnect()

asyncio.run(main())

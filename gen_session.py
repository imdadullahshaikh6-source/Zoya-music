# gen_session.py — VPS par chalao: python3 gen_session.py
# Assistant account ka naya STRING_SESSION banata hai (ye account bot ke saath VC me stream karega).
import asyncio
import sys

from pyrogram import Client


async def main():
    api_id = int(input("API_ID: ").strip())
    api_hash = input("API_HASH: ").strip()
    async with Client("gen", api_id=api_id, api_hash=api_hash, in_memory=True) as app:
        s = await app.export_session_string()
        print("\n=========== STRING_SESSION ===========\n")
        print(s)
        print("\n======================================")
        print("Isse .env me STRING_SESSION= ke aage paste karo. Kisi ko mat dikhana.")


if __name__ == "__main__":
    asyncio.run(main())

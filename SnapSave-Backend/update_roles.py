#!/usr/bin/env python
"""Script to update user roles in the database by phone number."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal
import models

def update_role_by_phone(phone_number: str, new_role: str):
    """Update a user's role by phone number."""
    db = SessionLocal()
    try:
        # Normalize phone number format
        normalized_phone = phone_number.strip()
        if not normalized_phone.startswith("+"):
            normalized_phone = "+" + normalized_phone

        user = db.query(models.User).filter(
            models.User.phone_number == normalized_phone
        ).first()

        if not user:
            # Try without +
            user = db.query(models.User).filter(
                models.User.phone_number.endswith(phone_number.replace("+", ""))
            ).first()

        if not user:
            print(f"[-] Error: User with phone '{phone_number}' not found in the database.")
            return False

        old_role = user.role
        user.role = new_role
        db.commit()
        db.refresh(user)

        print(f"[+] Success: User '{user.phone_number}' (ID: {user.id})")
        print(f"    Role updated: {old_role} -> {new_role}")
        return True

    except Exception as e:
        print(f"[-] Error occurred: {e}")
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    print("[*] Updating user roles...\n")

    # Update 9999999999 to ADMIN
    print("1. Setting +919999999999 to ADMIN")
    success1 = update_role_by_phone("+919999999999", "ADMIN")
    print()

    # Update 6969696969 to MODERATOR
    print("2. Setting +916969696969 to MODERATOR")
    success2 = update_role_by_phone("+916969696969", "MODERATOR")
    print()

    if success1 and success2:
        print("[+] All roles updated successfully!")
    else:
        print("[!] Some updates may have failed. Check the messages above.")

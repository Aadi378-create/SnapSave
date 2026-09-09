import sys
from database import SessionLocal
import models

def main():
    if len(sys.argv) < 2:
        print("Usage: python bootstrap_admin.py <email>")
        sys.exit(1)

    email = sys.argv[1].strip()
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.email == email).first()
        if not user:
            # Try case-insensitive search
            user = db.query(models.User).filter(models.User.email.ilike(email)).first()

        if not user:
            print(f"Error: User with email '{email}' not found in the database.")
            sys.exit(1)

        user.role = "ADMIN"
        db.commit()
        print(f"Success: User '{email}' (ID: {user.id}) has been promoted to ADMIN.")
    except Exception as e:
        print(f"Error occurred during admin bootstrapping: {e}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()

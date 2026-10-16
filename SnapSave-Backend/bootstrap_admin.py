import sys
import argparse
import re
from sqlalchemy import func
from database import SessionLocal
import models

def promote_admin(db, *, email=None, phone=None):
    if bool(email)==bool(phone):
        raise ValueError("Provide exactly one email or phone number")
    if phone:
        number=re.sub(r"[\s()-]","",phone)
        if re.fullmatch(r"[0-9]{10}",number):
            number="+91"+number
        if not re.fullmatch(r"\+[1-9][0-9]{7,14}",number):
            raise ValueError("Use a 10-digit Indian number or an international +countrycode number")
        normalized=models.User.phone_number
        for character in (" ","-","(",")","+"):
            normalized=func.replace(normalized,character,"")
        variants=[number[1:]]
        if number.startswith("+91") and len(number)==13:
            variants.append(number[3:])
        matches=db.query(models.User).filter(normalized.in_(variants)).all()
    else:
        matches=db.query(models.User).filter(func.lower(models.User.email)==email.strip().lower()).all()
    if len(matches)>1:
        raise ValueError("Multiple matching accounts exist; resolve the identity conflict before promotion")
    if not matches:
        raise ValueError("No account found. Sign in once before using the private administrator bootstrap")
    user=matches[0]
    user.role="ADMIN"
    db.commit()
    return user

def main():
    parser=argparse.ArgumentParser(description="Privately promote an existing account; Firebase verification remains required")
    parser.add_argument("email",nargs="?")
    parser.add_argument("--phone")
    args=parser.parse_args()
    with SessionLocal() as db:
        try:
            user=promote_admin(db,email=args.email,phone=args.phone)
            print(f"Administrator role saved for account {user.id}. Sign in using Firebase OTP.")
        except Exception as exc:
            db.rollback()
            print(f"Administrator provisioning failed: {exc}",file=sys.stderr)
            sys.exit(1)

if __name__ == "__main__":
    main()

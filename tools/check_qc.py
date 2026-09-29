"""QuantConnect 업로드 전 점검.

사용법: python tools/check_qc.py [qc_step 폴더 ...]
폴더를 안 주면 저장소 루트의 qc_step* 전부를 점검한다.

점검 항목
- 파일당 32,000자 한도(28,000자 넘으면 경고)
- main.py에 QCAlgorithm 상속 클래스가 있는지
- 내용이 똑같은 .py가 두 개 이상 있는지(다른 탭에 잘못 붙여 넣은 경우)
- 문법 오류
"""
import ast
import hashlib
import sys
from pathlib import Path

HARD_LIMIT = 32_000
SOFT_LIMIT = 28_000
ROOT = Path(__file__).resolve().parent.parent


def has_qc_algorithm(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                if name == "QCAlgorithm":
                    return True
    return False


def check_folder(folder):
    errors, warnings = [], []
    files = sorted(folder.glob("*.py"))
    if not files:
        warnings.append(f"{folder.name}: .py 파일 없음")
        return errors, warnings

    seen = {}
    for path in files:
        text = path.read_text(encoding="utf-8")
        n = len(text)
        label = f"{folder.name}/{path.name}"
        if n > HARD_LIMIT:
            errors.append(f"{label}: {n:,}자 (한도 {HARD_LIMIT:,} 초과)")
        elif n > SOFT_LIMIT:
            warnings.append(f"{label}: {n:,}자 (목표 {SOFT_LIMIT:,} 초과)")

        digest = hashlib.sha1(text.strip().encode()).hexdigest()
        if text.strip() and digest in seen:
            errors.append(f"{label}: {seen[digest]}와 내용이 같음 (잘못 붙여 넣었는지 확인)")
        seen.setdefault(digest, path.name)

        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as e:
            errors.append(f"{label}: 문법 오류 {e.lineno}행 {e.msg}")
            continue
        if path.name == "main.py" and not has_qc_algorithm(tree):
            errors.append(f"{label}: QCAlgorithm 상속 클래스 없음")

        print(f"  {label:<40} {n:>7,}자")

    if not (folder / "main.py").exists():
        errors.append(f"{folder.name}: main.py 없음")
    return errors, warnings


def main(args):
    folders = [Path(a) for a in args] or sorted(ROOT.glob("qc_step*"))
    all_errors, all_warnings = [], []
    for folder in folders:
        print(f"[{folder.name}]")
        errors, warnings = check_folder(folder)
        all_errors += errors
        all_warnings += warnings

    for w in all_warnings:
        print(f"경고: {w}")
    for e in all_errors:
        print(f"오류: {e}")
    print("통과" if not all_errors else f"오류 {len(all_errors)}건")
    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

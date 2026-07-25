import os
import sys

# Move to backend directory context to import main module
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(current_dir)
sys.path.append(backend_dir)

from database import get_db
from services.flipbook_service import delete_single_flipbook

def main():
    print("🧹 [CLEANUP] 테스트 더미 데이터 검사 및 일괄 삭제(GC) 시작...")
    # E2E 테스트 혹은 단위 테스트에서 사용한 더미 파일명 리스트
    target_titles = ["sample.pdf", "sample_test.pdf", "local_test.pdf", "E2E_TEST_local_test.pdf"]

    blobs_deleted = 0
    docs = get_db().collection("flipbooks").stream()
    
    for doc in docs:
        data = doc.to_dict()
        if not data:
            continue
            
        title = data.get("title", "")
        # 특정 파일명이거나, E2E_TEST 접두사로 시작하는 경우 삭제 대상을 판별
        if title in target_titles or title.startswith("E2E_TEST_"):
            print(f"🗑 발견된 찌꺼기 데이터: {title} (ID: {doc.id}) -> 철거 진행")
            try:
                delete_single_flipbook(doc.id)
                blobs_deleted += 1
            except Exception as e:
                print(f"❌ 삭제 중 에러 발생: {doc.id} - {str(e)}")
                
    if blobs_deleted == 0:
        print("💡 [CLEANUP] 지울 찌꺼기 데이터가 발견되지 않았습니다.")
    else:
        print(f"✅ [CLEANUP] 총 {blobs_deleted}개의 테스트 임시 문서 및 Cloud Storage 블롭을 완전히 제거했습니다.")

if __name__ == "__main__":
    main()

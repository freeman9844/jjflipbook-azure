# GitHub Flow 기반 협업 방법론 (Best Practices with Git Worktree)

본 문서는 운영 중인 프로덕션 코드(상용 서비스)를 다룰 때, 서비스에 악영향을 주지 않고 안전하게 코드를 개선 및 배포하기 위한 **GitHub Flow** 협업 방식의 핵심 프로세스를 정리한 가이드입니다. 

특히 본 프로젝트에서는 프론트엔드/백엔드 의존성 꼬임을 방지하고 병렬 작업을 원활하게 하기 위해 **`git worktree`**를 적극 활용합니다.

## 🎯 왜 GitHub Flow와 Worktree를 써야 하나요?
`main` 브랜치에 직접 코드를 작성하고 Push하는 것은 "실제 운영되는 서버에 즉시 코드를 덮어쓰는 것"과 같아 매우 위험합니다. 버그나 오타 하나가 서비스 장애로 직결될 수 있습니다. 
따라서 우리는 항상 **"이슈(Issue) 등록 -> 격리된 브랜치(Worktree) 작업 -> PR 코드 리뷰 -> 병합(Merge)"** 이라는 안전장치를 통과해야 합니다.
추가로 `git worktree`를 사용하면 브랜치 전환 시 발생하는 `node_modules`나 `venv` 충돌 문제를 원천 차단할 수 있습니다.

---

## 🚀 GitHub Flow + Worktree 6단계 워크플로우

### Step 1. 작업 방향 정의 (Issue 등록)
코드 작성 전, 무엇을 왜 수정할 것인지 GitHub Issues에 등록하여 목표를 명확히 합니다.
* **명령어:** `gh issue create --title "[분류] 제목" --body "상세내용"`

### Step 2. 최신화 및 격리된 작업 환경(Worktree) 생성
기존 폴더에서 브랜치를 바꾸는 대신, 현재 작업 폴더 바깥에 완전히 독립된 새 폴더(Worktree)를 생성하여 작업합니다.
*(기존 메인 프로젝트 폴더는 항상 `main` 브랜치 전용으로 깨끗하게 유지하는 것을 권장합니다.)*

* 브랜치 네이밍: `종류/이슈번호-간단한-설명` (예: `feature/3-login-ui`, `perf/1-async-upload`)
```bash
# 1. 원격 저장소의 최신 상태를 가져옵니다.
git fetch origin

# 2. 상위 폴더(../)에 'perf-1-async-upload'라는 독립된 작업 폴더를 만들고, 
# 'perf/1-async-upload' 브랜치를 생성하여 연결합니다. (origin/main 기준)
git worktree add -b perf/1-async-upload ../perf-1-async-upload origin/main

# 3. 새로 생성된 작업 폴더로 이동합니다.
cd ../perf-1-async-upload
```

> **⚠️ 주의사항 (Worktree 초기화)**
> Worktree로 생성된 새 폴더는 `.gitignore` 처리된 파일(`.env`, `node_modules`, `venv` 등)이 포함되지 않은 깨끗한 코드 상태입니다. 따라서 이동 직후 다음 과정이 필요할 수 있습니다.
> * **환경 변수 복사:** 기존 폴더에서 `.env` 파일을 복사해옵니다. (예: `cp ../flip_text_001/.env .env`)
> * **의존성 설치:** 프론트엔드는 `npm install`, 백엔드는 `pip install -r requirements.txt` 등을 실행하여 해당 브랜치에 맞는 독립된 환경을 구성합니다.

### Step 3. 개발 및 커밋 (Commit)
새로 생성된 작업 폴더 내에서 마음껏 코드를 수정하고 테스트합니다. 이 폴더만의 독립적인 `node_modules`나 `venv`가 유지되므로 다른 작업과 꼬이지 않습니다.
```bash
git add .
git commit -m "perf: 업로드 속도 개선 (resolves #1)"
```
> **Tip:** 메시지에 `resolves #이슈번호` 또는 `fixes #이슈번호`를 적어두면 나중에 병합 시 해당 이슈가 자동으로 닫힙니다.

### Step 4. 원격 저장소에 반영 (Push)
내 컴퓨터에서 작업한 브랜치를 GitHub 서버로 올려보냅니다.
```bash
git push -u origin perf/1-async-upload
```

### Step 5. 코드 리뷰 요청 (Pull Request 생성)
가장 중요한 단계입니다. "내가 작업한 브랜치를 `main`에 합쳐도 될지 확인해줘!" 라고 리뷰를 요청합니다. 이 과정에서 자동화된 테스트(CI/CD)나 동료의 코드 리뷰가 진행됩니다.
* **명령어:** 
```bash
gh pr create --title "perf: 업로드 속도 개선 (resolves #1)" --body "상세작업내용" --base main
```

### Step 6. 최종 병합 및 Worktree 정리 (Merge & Cleanup)
GitHub 화면에서 코드에 문제가 없다고 판단되면 `Merge pull request`를 눌러 `main`에 합칩니다. (보통 커밋을 하나로 깔끔하게 묶는 `Squash and Merge`를 권장합니다.)
이후 역할이 끝난 로컬의 작업 폴더(Worktree)와 브랜치를 삭제합니다.
```bash
# 1. 원래의 메인 프로젝트 폴더로 복귀합니다.
cd ../flip_text_001

# 2. 메인 브랜치를 최신 상태로 동기화합니다. (PR 병합 내역을 로컬에 반영)
git pull origin main

# 3. 더 이상 필요 없는 worktree 폴더를 안전하게 삭제합니다.
git worktree remove ../perf-1-async-upload

# 4. 로컬 브랜치를 삭제합니다. (main이 최신화되어 있어야 정상 삭제됩니다.)
git branch -d perf/1-async-upload
```

---

## 💡 요약 규칙 (Golden Rules)
1. **Never commit to main**: 절대 `main` 브랜치에 직접 커밋하거나 푸시하지 마세요. (메인 폴더는 항상 깨끗한 상태를 유지합니다.)
2. **One Branch(Worktree) = One Issue**: 하나의 작업 폴더에서는 반드시 하나의 이슈(기능)만 처리하세요. 환경 격리의 이점을 최대한 살리세요.
3. **Review is mandatory**: 코드가 완벽해 보여도 반드시 PR을 통해 본인 혹은 동료의 리뷰 과정을 거친 후 병합하세요.

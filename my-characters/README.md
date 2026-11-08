# 내 캐릭터 변환 작업실

그림 한 장(전신/반신 일러스트)을 LivLiv Player가 움직일 수 있는 **LivLiv v4 모델 패키지**로 바꾸는 도구입니다.
배경을 지우고, 머리·눈·눈썹·입을 찾아 레이어로 잘라내고, `model.json`을 쓰고, 스키마로 검사한 뒤 `.livliv`로 묶습니다.

변환된 캐릭터는 고개 돌리기·끄덕임·기울임, 눈 깜빡임, 시선 이동, 립싱크(마이크/오디오), 숨쉬기, 웹캠 얼굴 추적이 모두 동작합니다.

---

## 1. 그림 넣기

`my-characters/source/` 에 PNG(또는 JPG/WEBP)를 넣습니다. 파일 이름이 캐릭터 id가 됩니다.

```bash
cp ~/내그림/mina.png my-characters/source/mina.png
```

**잘 맞는 그림**

- 정면을 보는 반신 또는 전신 애니메이션풍 일러스트
- 배경이 단색이거나 이미 투명한 것 (단색이면 자동으로 지웁니다)
- 눈·입이 가려지지 않은 것, 눈을 뜨고 있는 것
- 가로·세로 1000px 이상 권장

**잘 안 맞는 그림**: 옆얼굴·뒷모습, 여러 명이 함께 있는 그림, 사진, 배경이 복잡한 그림.

## 2. 변환

```bash
npm run my:convert
```

`source/` 안의 모든 그림을 변환합니다. 한 장만 하려면 경로를 주면 됩니다.

```bash
npm run my:convert -- my-characters/source/mina.png --name "미나" --author "내이름"
```

결과는 `my-characters/out/mina/` 폴더와 `my-characters/out/mina.livliv` 파일입니다.

## 3. 확인하고 고치기

```bash
npm run my:serve
```

- **보정 화면** http://127.0.0.1:8080/tools/mark.html — 찾아낸 머리 타원, 눈·눈썹·입 상자, 턱선을 드래그로 고칩니다.
  고친 뒤 **Convert again** 을 누르면 그 자리에서 다시 변환됩니다.
- **미리보기** http://127.0.0.1:8080/tools/preview.html — 실제 플레이어로 재생합니다. 포즈 슬라이더, 동작 버튼,
  마이크 립싱크, 웹캠 추적을 눌러볼 수 있습니다.

화면 없이 확인하려면 헤드리스 크로미움으로 12가지 포즈를 그려 PNG로 저장합니다.

```bash
npm run my:render          # out/<id>/_poses/*.png
```

`out/<id>/_marks.png` 는 무엇을 어떻게 찾았는지 그림 위에 그려 놓은 것입니다. 먼저 이 파일을 보세요.

---

## 명령어

| 명령 | 하는 일 |
|---|---|
| `npm run my:convert` | `source/` 의 그림을 전부 변환 |
| `npm run my:convert -- <그림> [옵션]` | 한 장만 변환 |
| `npm run my:serve` | 보정 화면 + 미리보기 서버 (127.0.0.1:8080) |
| `npm run my:render` | 헤드리스 브라우저로 포즈 그려 보기 |
| `npm run my:check -- my-characters/out/<id>` | 패키지를 스키마와 FORMAT.md 규칙으로 검사 |
| `npm run my:calibrate` | 기본 캐릭터 21종으로 탐지 정확도 측정 (도구 손볼 때) |

### 변환 옵션

| 옵션 | 뜻 |
|---|---|
| `--name "이름"` | 패키지에 들어갈 캐릭터 이름 |
| `--id <id>` | 파일 이름 대신 쓸 id |
| `--author "이름"` / `--license <SPDX>` | `meta.author` / `meta.license` |
| `--mark "텍스트"` | 오른쪽 아래에 그릴 나만의 워터마크 (24자까지) |
| `--max-side 2048` | 캔버스 최대 변 길이 (기본 2048). 원본이 이보다 작으면 그대로 씁니다 |
| `--bg-tol 22` | 배경으로 칠 색의 허용 오차. 배경이 안 지워지면 올리고, 캐릭터가 깎이면 내립니다 |
| `--bust 0.7` | 가슴 스프링 세기 (0~1, 기본 0) |
| `--glasses` | 안경 쓴 얼굴 (눈꺼풀 곡선 처리가 달라집니다) |
| `--no-lids` | 감은 눈 레이어를 만들지 않음 (눈을 찌그러뜨려 감습니다) |
| `--redetect` | 저장된 marks를 무시하고 다시 탐지 |
| `--no-pack` | 폴더만 만들고 `.livliv` 는 만들지 않음 |

---

## 만들어지는 것

```
my-characters/
  source/<id>.png        넣은 그림
  marks/<id>.json        찾아낸 위치 (직접 고쳐도 됩니다. 있으면 다음 변환 때 그대로 씁니다)
  out/<id>/
    model.json           LivLiv v4 매니페스트
    textures/*.webp      레이어 그림 (눈 마스크만 무손실 PNG)
    avatar.webp          96x96 얼굴
    cover.webp           정지 화면용 그림
    _marks.png           탐지 결과를 그려 놓은 확인용 그림
    _canvas.webp         배경을 지운 캔버스 (보정 화면이 씁니다)
    _poses/*.png         my:render 가 그린 포즈들
  out/<id>.livliv        위 폴더를 한 파일로 묶은 것 (`_`로 시작하는 파일과 cover는 뺍니다)
```

레이어는 `body`, `face`, 눈 좌우(`eye_L/R`, `iris_L/R`, 감은 눈 `eye_L/R_closed`), `mouth`(5프레임: 다묾·반·열림·오·이),
그리고 눈썹을 분리할 수 있었다면 `brows` 입니다.

## 페이지에 넣기

```js
import { Player } from '@livliv-dev/player'

const player = new Player(document.querySelector('canvas'))
await player.load('my-characters/out/mina/')      // 또는 'mina.livliv'

player.act('nod')
player.params.mouthOpen = 0.6
```

립싱크와 얼굴 추적은 [../API.md](../API.md) 를 보세요.

---

## 어디까지 자동인가

기본 캐릭터 21종의 실제 값과 비교해 측정한 오차입니다 (`npm run my:calibrate`, 단위는 머리 반지름).

| 항목 | 중앙값 오차 | 성공률 |
|---|---|---|
| 머리 크기 `head.ry` / `head.rx` | 0.05 / 0.07 | 21/21 |
| 머리 중심 `head.cx` | 0.02 | 21/21 |
| 턱선 `neck_y` | 0.14 | 21/21 |
| 눈 위치 | 0.06 | 17/21 |
| 입 위치 | 0.08 | 14/21 (나머지는 비례로 추정) |

눈 위치가 머리 기하를 결정합니다. 눈만 제대로 잡히면 나머지는 거의 맞습니다. **`_marks.png` 에서 눈 상자(초록)가
눈에 맞는지 먼저 보세요.** 어긋났다면 보정 화면에서 눈 상자 두 개만 옮기고 다시 변환하면 됩니다.

사람이 아닌 캐릭터(동물·마스코트)는 눈을 못 찾는 경우가 많습니다. 이때도 보정 화면에서 직접 잡아주면 됩니다.

## 안 되는 것

그림 한 장에서 만들 수 없는 것들입니다. 억지로 만들지 않고 비워 둡니다.

- **표정** (`smile`, `shy`, `angry`, `sad` …): 표정마다 다시 그린 얼굴이 필요합니다. `expressions` 는 빈 배열입니다.
- **머리카락 흔들림**: 머리카락을 앞/옆/뒤로 나눠 자를 수 없어, 머리 전체가 한 덩어리로 같이 움직입니다.
- **눈썹 움직임**: 앞머리에 가려진 눈썹은 분리할 수 없습니다. 분리된 경우에만 `brows` 레이어가 생깁니다.
- **입 모양**: 원본에 다문 입 하나뿐이므로 벌어진 입은 머리 크기에 맞춰 합성합니다. 그려진 입만큼 자연스럽지는 않습니다.

이것들까지 제대로 된 모델이 필요하면 [livliv.ai](https://livliv.ai) 에서 그림 한 장으로 만들고 **Model package**(`.livliv`)를
내려받으면 됩니다. 같은 플레이어가 그대로 재생합니다.

## 저작권

변환 결과에는 LivLiv 워터마크를 넣지 않습니다(FORMAT.md §3: 요청하지 않은 패키지에 마크를 그리지 않음). 넣은 그림의
권리는 그대로 넣은 사람 것이고, `--author` / `--license` 로 `meta` 에 적어 둘 수 있습니다. 이 저장소에 딸린
`characters/` 의 기본 캐릭터들은 별도 라이선스([../characters/LICENSE.md](../characters/LICENSE.md))이며 변환 입력으로 써서
배포하면 안 됩니다.

from __future__ import annotations

import argparse
import html
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


OUTPUT_DEFAULTS = {
    "zh": Path("docs") / "safety_helmet_demo_script_2min_zh.docx",
    "en": Path("docs") / "safety_helmet_demo_script_2min_en.docx",
}

TITLE_BY_LANGUAGE = {
    "zh": "安全帽检测系统两分钟演示稿",
    "en": "Two-Minute Demo Script for the Safety Helmet Detection System",
}


def _paragraph_xml(
    text: str,
    *,
    bold: bool = False,
    size_half_points: int = 24,
    align: str | None = None,
) -> str:
    paragraph_props = []
    if align:
        paragraph_props.append(f'<w:jc w:val="{align}"/>')
    ppr = f"<w:pPr>{''.join(paragraph_props)}</w:pPr>" if paragraph_props else ""

    run_props = [f'<w:sz w:val="{size_half_points}"/>', f'<w:szCs w:val="{size_half_points}"/>']
    if bold:
        run_props.append("<w:b/>")
        run_props.append("<w:bCs/>")

    escaped = html.escape(text)
    return (
        "<w:p>"
        f"{ppr}"
        "<w:r>"
        f"<w:rPr>{''.join(run_props)}</w:rPr>"
        f'<w:t xml:space="preserve">{escaped}</w:t>'
        "</w:r>"
        "</w:p>"
    )


def _document_xml(paragraphs: list[str]) -> str:
    body = "".join(paragraphs) + (
        "<w:sectPr>"
        '<w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
        'w:header="708" w:footer="708" w:gutter="0"/>'
        "</w:sectPr>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:o="urn:schemas-microsoft-com:office:office" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
        'xmlns:v="urn:schemas-microsoft-com:vml" '
        'xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:w10="urn:schemas-microsoft-com:office:word" '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
        'xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" '
        'xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk" '
        'xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml" '
        'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
        'mc:Ignorable="w14 wp14">'
        f"<w:body>{body}</w:body>"
        "</w:document>"
    )


def _content_types_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/docProps/app.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )


def _root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
        'Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" '
        'Target="docProps/app.xml"/>'
        "</Relationships>"
    )


def _document_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        "</Relationships>"
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        "<w:name w:val=\"Normal\"/>"
        '<w:qFormat/>'
        "</w:style>"
        "</w:styles>"
    )


def _core_xml(title: str) -> str:
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    escaped_title = html.escape(title)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{escaped_title}</dc:title>"
        "<dc:creator>OpenAI Codex</dc:creator>"
        "<cp:lastModifiedBy>OpenAI Codex</cp:lastModifiedBy>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{created}</dcterms:modified>'
        "</cp:coreProperties>"
    )


def _app_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        "<Application>Microsoft Office Word</Application>"
        "</Properties>"
    )


def _build_lines(language: str) -> list[tuple[str, dict[str, object]]]:
    if language == "en":
        title = TITLE_BY_LANGUAGE["en"]
        return [
            (title, {"bold": True, "size_half_points": 30, "align": "center"}),
            ("Project: Safety Helmet Detection System", {"size_half_points": 22, "align": "center"}),
            ("Recommended Duration: About 2 Minutes", {"size_half_points": 22, "align": "center"}),
            ("", {"size_half_points": 22}),
            ("1. Demo Goal", {"bold": True, "size_half_points": 26}),
            (
                "Use two minutes to explain what the system does, how it detects helmet compliance in real time, and how the results support safety management.",
                {"size_half_points": 22},
            ),
            ("", {"size_half_points": 22}),
            ("2. Voiceover Script", {"bold": True, "size_half_points": 26}),
            (
                "Hello everyone. In the next two minutes, I will introduce this safety helmet detection system. The purpose of this system is to turn ordinary video monitoring into a real-time, visible, and manageable safety tool.",
                {"size_half_points": 22},
            ),
            (
                "What you are seeing now is the live camera view. The system continuously reads the video stream and automatically determines whether a person is wearing a safety helmet.",
                {"size_half_points": 22},
            ),
            (
                "If the person is wearing a helmet, the system shows a green box. If the person is not wearing a helmet, the system immediately shows a red box. This allows supervisors to identify potential safety violations at a glance.",
                {"size_half_points": 22},
            ),
            (
                "This is not just a static image refresh. It is a real-time detection workflow designed for live monitoring. As people move in and out of the scene, the boxes update with the video, which makes the system suitable for both site demonstrations and daily safety supervision.",
                {"size_half_points": 22},
            ),
            (
                "When the system keeps detecting a no-helmet condition, it can generate an alert record in the background and save the related evidence, including the image, timestamp, camera information, and other traceable data.",
                {"size_half_points": 22},
            ),
            (
                "Managers can then open the dashboard to review alerts, check camera status, and view operational reports. In other words, this system does not only detect a problem. It also supports the full process of finding, recording, reviewing, and following up on that problem.",
                {"size_half_points": 22},
            ),
            (
                "To summarize, this solution delivers three key values. First, it identifies no-helmet behavior in real time. Second, it presents the result clearly with green and red boxes. Third, it upgrades standard video monitoring into a safety management platform that is easier to track, review, and improve. Thank you.",
                {"size_half_points": 22},
            ),
            ("", {"size_half_points": 22}),
            ("3. Suggested Demo Timing", {"bold": True, "size_half_points": 26}),
            ("0:00 - 0:20  Introduce the system and explain the business goal.", {"size_half_points": 22}),
            ("0:20 - 0:50  Show the live view and explain green box versus red box.", {"size_half_points": 22}),
            ("0:50 - 1:20  Switch between helmet and no-helmet scenarios in front of the camera.", {"size_half_points": 22}),
            ("1:20 - 1:45  Show the alert record, evidence snapshot, and camera information.", {"size_half_points": 22}),
            ("1:45 - 2:00  Close with a short value summary.", {"size_half_points": 22}),
            ("", {"size_half_points": 22}),
            ("4. Suggested On-Screen Actions", {"bold": True, "size_half_points": 26}),
            ("1. Open the browser live preview page or the desktop real-time viewer.", {"size_half_points": 22}),
            ("2. Step into the camera view while wearing a helmet to show the green box.", {"size_half_points": 22}),
            ("3. Remove the helmet or switch to a no-helmet example to show the red box.", {"size_half_points": 22}),
            ("4. End by showing the dashboard with alert history or evidence records.", {"size_half_points": 22}),
        ]

    title = TITLE_BY_LANGUAGE["zh"]
    return [
        (title, {"bold": True, "size_half_points": 32, "align": "center"}),
        ("项目：Safety Helmet Detection System", {"size_half_points": 22, "align": "center"}),
        ("建议时长：约 2 分钟", {"size_half_points": 22, "align": "center"}),
        ("", {"size_half_points": 22}),
        ("一、演示目标", {"bold": True, "size_half_points": 26}),
        ("用两分钟清楚说明系统能做什么、现场怎么识别、识别结果如何形成管理闭环。", {"size_half_points": 22}),
        ("", {"size_half_points": 22}),
        ("二、口播稿", {"bold": True, "size_half_points": 26}),
        (
            "大家好，下面我用两分钟介绍这套安全帽检测系统。这个系统的核心目标，是把现场视频变成可实时查看、可自动识别、可留痕复核的安全管理工具。",
            {"size_half_points": 22},
        ),
        (
            "首先大家现在看到的是实时摄像头画面。系统会持续读取视频内容，并自动判断现场人员是否佩戴安全帽。如果识别到已经佩戴安全帽，目标会显示绿色框；如果识别到未佩戴安全帽或存在违规风险，目标就会立即显示红色框，方便值班人员第一时间发现异常。",
            {"size_half_points": 22},
        ),
        (
            "这套预览不是单纯的截图刷新，而是面向实时画面的检测链路。人员在移动、转身或者进出画面时，框会跟着变化，所以更适合做现场演示，也更适合日常值守场景。",
            {"size_half_points": 22},
        ),
        (
            "当系统连续判断存在未佩戴安全帽的情况时，后台会自动生成告警记录，并保存对应的截图、时间、摄像头信息以及相关证据。这样后面不管是人工复核、责任追踪，还是留档统计，都有清晰依据。",
            {"size_half_points": 22},
        ),
        (
            "在管理后台里，管理人员还可以查看告警列表、人工复核结果、摄像头状态和统计报表。也就是说，这个系统不只是看见问题，而是把发现、记录、复核和整改串成一个完整流程。",
            {"size_half_points": 22},
        ),
        (
            "总结一下，这套系统的价值有三点：第一，实时发现未戴安全帽行为；第二，用红绿框直观展示当前风险状态；第三，把普通视频监控升级成可管理、可追踪、可复盘的安全管理平台。我的演示到这里，谢谢大家。",
            {"size_half_points": 22},
        ),
        ("", {"size_half_points": 22}),
        ("三、建议演示节奏", {"bold": True, "size_half_points": 26}),
        ("0:00 - 0:20  开场，说明系统定位和目标。", {"size_half_points": 22}),
        ("0:20 - 0:50  展示实时画面，说明绿色框代表戴帽、红色框代表未戴帽。", {"size_half_points": 22}),
        ("0:50 - 1:20  现场切换“戴帽 / 不戴帽”状态，演示框颜色变化。", {"size_half_points": 22}),
        ("1:20 - 1:45  展示后台告警记录、截图和摄像头信息。", {"size_half_points": 22}),
        ("1:45 - 2:00  用三点总结系统价值，结束演示。", {"size_half_points": 22}),
        ("", {"size_half_points": 22}),
        ("四、演示时可配合的操作", {"bold": True, "size_half_points": 26}),
        ("1. 打开本地浏览器实时预览页或桌面实时窗口。", {"size_half_points": 22}),
        ("2. 先以佩戴安全帽状态进入镜头，展示绿色框。", {"size_half_points": 22}),
        ("3. 再切换成未佩戴安全帽状态，展示红色框。", {"size_half_points": 22}),
        ("4. 最后切到后台页面，展示告警记录和统计信息。", {"size_half_points": 22}),
    ]


def _build_paragraphs(language: str) -> list[str]:
    return [_paragraph_xml(text, **options) for text, options in _build_lines(language)]


def write_demo_script_doc(output_path: Path, language: str) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    title = TITLE_BY_LANGUAGE[language]

    with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", _content_types_xml())
        docx.writestr("_rels/.rels", _root_rels_xml())
        docx.writestr("docProps/core.xml", _core_xml(title))
        docx.writestr("docProps/app.xml", _app_xml())
        docx.writestr("word/document.xml", _document_xml(_build_paragraphs(language)))
        docx.writestr("word/styles.xml", _styles_xml())
        docx.writestr("word/_rels/document.xml.rels", _document_rels_xml())

    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a 2-minute demo script Word document.")
    parser.add_argument(
        "--language",
        choices=("zh", "en"),
        default="zh",
        help="Document language. Defaults to zh.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output .docx path. If omitted, a language-based default is used.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_value = args.output or str(OUTPUT_DEFAULTS[args.language])
    output_path = Path(output_value).resolve()
    written = write_demo_script_doc(output_path, args.language)
    print(f"Generated Word document: {written}")


if __name__ == "__main__":
    main()

---
name: {{NAME_KEBAB}}
display_name: {{TODO_DISPLAY_NAME_ZH}}
display_name_en: {{TODO_DISPLAY_NAME_EN}}
description: {{TODO_USE_AND_TRIGGER_WORDS_THIS_IS_HOW_AI_DECIDES_TO_CALL}}
description_zh: {{TODO_SHORT_ZH_INTRO_FOR_DETAIL_PAGE}}
description_en: {{TODO_SHORT_EN_INTRO_FOR_DETAIL_PAGE}}
version: 1.0.0
author: {{TODO_AUTHOR}}
examples_zh:
  - "{{TODO_EXAMPLE_1_ZH}}"
  - "{{TODO_EXAMPLE_2_ZH}}"
  - "{{TODO_EXAMPLE_3_ZH}}"
examples_en:
  - "{{TODO_EXAMPLE_1_EN}}"
  - "{{TODO_EXAMPLE_2_EN}}"
  - "{{TODO_EXAMPLE_3_EN}}"
---

# {{TODO_SKILL_TITLE}}

## 前置条件

{{TODO_PREREQUISITES_CONNECTOR_INPUTS_PERMISSIONS}}

## 执行步骤

当用户需要 {{TODO_TRIGGER_SCENARIO}} 时，按以下步骤执行：

1. {{TODO_STEP_1}}
2. {{TODO_STEP_2}}
3. {{TODO_STEP_3}}

## 失败处理

- {{TODO_FAILURE_CASE_1}} → {{TODO_FALLBACK}}
- {{TODO_FAILURE_CASE_2}} → {{TODO_FALLBACK}}

## 子资源（按需创建）

- `references/`：长知识文档，正文用 `@references/xxx.md` 引用
- `scripts/`：确定性逻辑，AI 通过 Bash 调用
- `templates/`：可复用的输出模板

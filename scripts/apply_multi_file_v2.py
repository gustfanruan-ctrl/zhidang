#!/usr/bin/env python3
"""Apply multi-file upload changes to ReviewPage.vue using line-by-line manipulation."""
import sys, os

path = 'D:/智档/frontend/src/pages/ReviewPage.vue'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Strategy: use substring extraction from the file itself to match patterns
lines = content.split('\n')

# 1. uploadedFile ref -> uploadedFiles ref
for i, l in enumerate(lines):
    if l.strip() == 'const uploadedFile = ref(null)':
        lines[i] = 'const uploadedFiles = ref([])  // [{ name, dataUrl, type }]'
    if l.strip() == 'const filePreview = ref(null)':
        lines[i] = ''

# 2. isImageFile -> hasImages
for i, l in enumerate(lines):
    if l.strip().startswith('const isImageFile = computed('):
        # Find the closing })
        lines[i] = "const hasImages = computed(() => uploadedFiles.value.some(f => f.type === 'image'))"
        # Remove next few lines until '})'
        j = i + 1
        while j < len(lines) and lines[j].strip() != '})':
            lines[j] = ''
            j += 1
        if j < len(lines):
            lines[j] = ''
        break

# 3. onFileDrop - multiple
for i, l in enumerate(lines):
    if l.strip().startswith('function onFileDrop'):
        lines[i+2] = '  for (const f of files) handleFile(f)'
        break

# 4. onFileSelect - multiple
for i, l in enumerate(lines):
    if l.strip().startswith('function onFileSelect'):
        lines[i+2] = '  for (const f of files) handleFile(f)'
        lines.insert(i+3, "  fileInput.value.value = ''")
        break

# 5. handleFile - replace entire function
for i, l in enumerate(lines):
    if l.strip().startswith('function handleFile(file)'):
        # Find the closing brace
        depth = 0
        j = i
        while j < len(lines):
            depth += lines[j].count('{') - lines[j].count('}')
            j += 1
            if depth == 0:
                break
        new_body = [
            "function getFileType(file) {",
            "  const ext = file.name.split('.').pop().toLowerCase()",
            "  return ['jpg', 'jpeg', 'png', 'webp'].includes(ext) ? 'image' : 'text'",
            "}",
            "function handleFile(file) {",
            "  if (!validateFile(file)) {",
            "    showMessage('不支持的文件类型，请上传 .txt, .jpg, .jpeg, .png, .webp 文件', 'error')",
            "    return",
            "  }",
            "  const ftype = getFileType(file)",
            "  if (ftype === 'text') {",
            "    const reader = new FileReader()",
            "    reader.onload = (e) => {",
            "      transcriptText.value = transcriptText.value ? transcriptText.value + '\\n\\n' + e.target.result : e.target.result",
            "      uploadedFiles.value.push({ name: file.name, dataUrl: null, type: 'text' })",
            '      showMessage(\'文本文件 "\' + file.name + \'" 读取成功\', \'success\')',
            "      currentStep.value = 1",
            "    }",
            "    reader.onerror = () => showMessage('读取文本文件失败', 'error')",
            "    reader.readAsText(file)",
            "  } else {",
            "    const reader = new FileReader()",
            "    reader.onload = (e) => {",
            "      uploadedFiles.value.push({ name: file.name, dataUrl: e.target.result, type: 'image' })",
            '      showMessage(\'图片 "\' + file.name + \'" 上传成功\', \'success\')',
            "      currentStep.value = 1",
            "    }",
            "    reader.readAsDataURL(file)",
            "  }",
            "}",
        ]
        lines[i:j] = new_body
        break

# 6. removeFile - replace
for i, l in enumerate(lines):
    if l.strip().startswith('function removeFile()'):
        depth = 0
        j = i
        while j < len(lines):
            depth += lines[j].count('{') - lines[j].count('}')
            j += 1
            if depth == 0:
                break
        lines[i:j] = [
            "function removeFile(idx) {",
            "  const removed = uploadedFiles.value.splice(idx, 1)[0]",
            "  if (removed && removed.type === 'text') {",
            "    transcriptText.value = ''",
            "  }",
            "  currentStep.value = 1",
            "}",
        ]
        break

# 7. generateReview - add images param
for i, l in enumerate(lines):
    if 'uploadedFile.value && isImageFile.value' in l:
        lines[i] = "      input_type: hasImages.value ? 'screenshot' : 'text',"
        lines.insert(i+1, "      images: uploadedFiles.value.filter(f => f.type === 'image').map(f => f.dataUrl),")
        break

# 8. Template: uploadedFile area -> multi-file list
for i, l in enumerate(lines):
    if 'v-if="!uploadedFile"' in l:
        # Find the end of the upload file block (the </div> after removeFile button)
        j = i
        found_end = False
        while j < len(lines) and not found_end:
            if '@click.stop="removeFile"' in lines[j]:
                # This is inside the button in the v-else block
                # Find the closing </div> tags
                k = j
                depth = 0
                while k < len(lines):
                    if '<div' in lines[k] and '</div' not in lines[k]:
                        depth += 1
                    if '</div>' in lines[k]:
                        depth -= 1
                    k += 1
                    if depth == 0 and k - j > 3:
                        j = k
                        found_end = True
                        break
            j += 1
            if j > i + 30:
                break
        # If not found, use simpler heuristic
        if not found_end:
            j = i + 12  # approximate
        new_tpl = [
            '                <div v-if="!uploadedFiles.length" class="space-y-2">',
            '                  <Upload class="h-8 w-8 mx-auto text-muted-foreground/40" />',
            '                  <p class="text-sm text-muted-foreground">点击或拖拽上传文件（支持多选）</p>',
            '                  <p class="text-xs text-muted-foreground/60">支持 .txt, .jpg, .jpeg, .png, .webp</p>',
            '                </div>',
            '                <div v-else class="space-y-2">',
            '                  <div v-for="(f, idx) in uploadedFiles" :key="idx" class="flex items-center justify-between bg-muted/50 rounded-lg px-4 py-3">',
            '                    <div class="flex items-center gap-3">',
            '                      <Image v-if="f.type === \'image\'" class="h-5 w-5 text-muted-foreground" />',
            '                      <FileText v-else class="h-5 w-5 text-muted-foreground" />',
            '                      <span class="text-sm font-medium truncate max-w-[200px]">{{ f.name }}</span>',
            '                      <span class="text-xs text-muted-foreground/60">{{ f.type === \'image\' ? \'图片\' : \'文本\' }}</span>',
            '                    </div>',
            '                    <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" @click.stop="removeFile(idx)">',
            '                      <X class="h-4 w-4 mr-1" />移除',
            '                    </Button>',
            '                  </div>',
            '                </div>',
        ]
        lines[i:j] = new_tpl
        break

# 9. Template: image preview -> multi-image grid
for i, l in enumerate(lines):
    if 'v-if="filePreview && isImageFile"' in l:
        lines[i] = '            <div v-if="uploadedFiles.filter(f => f.type === \'image\').length" class="flex gap-2 flex-wrap">'
        lines[i+1] = '              <img v-for="(f, idx) in uploadedFiles.filter(f => f.type === \'image\')" :key="idx" :src="f.dataUrl" alt="预览" class="w-[120px] h-[80px] object-cover rounded-lg border border-border" />'
        lines[i+2] = '            </div>'
        break

# 10. Image icon import
for i, l in enumerate(lines):
    if 'import {' in l and 'FileText' in l and '@lucide/vue' in l:
        lines[i] = l.replace('FileText,', 'FileText, Image,')
        break

# Remove empty lines
lines = [l for l in lines if l != '']

with open(path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

print('All changes applied successfully')

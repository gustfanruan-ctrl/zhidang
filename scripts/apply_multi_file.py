#!/usr/bin/env python3
"""Apply multi-file upload changes to ReviewPage.vue."""
import sys

with open('D:/智档/frontend/src/pages/ReviewPage.vue', 'r', encoding='utf-8') as f:
    c = f.read()

changes = 0

# 1. uploadedFile -> uploadedFiles (ref declaration)
c = c.replace(
    'const uploadedFile = ref(null)\nconst filePreview = ref(null)',
    'const uploadedFiles = ref([])  // [{ name, dataUrl, type }]'
)
changes += 1

# 2. isImageFile -> hasImages
old_comp = (
    'const isImageFile = computed(() => {\n'
    '  if (!uploadedFile.value) return false\n'
    "  const ext = uploadedFile.value.name.split('.').pop().toLowerCase()\n"
    '  return [\'jpg\', \'jpeg\', \'png\', \'webp\'].includes(ext)\n'
    '})'
)
new_comp = "const hasImages = computed(() => uploadedFiles.value.some(f => f.type === 'image'))"
assert old_comp in c, 'isImageFile not found'
c = c.replace(old_comp, new_comp)
changes += 1

# 3. onFileDrop - handle multiple
old_drop = (
    'function onFileDrop(e) {\n'
    '  isDragOver.value = false\n'
    '  const files = e.dataTransfer.files\n'
    '  if (files.length > 0) handleFile(files[0])\n'
    '}'
)
new_drop = (
    'function onFileDrop(e) {\n'
    '  isDragOver.value = false\n'
    '  const files = e.dataTransfer.files\n'
    '  for (const f of files) handleFile(f)\n'
    '}'
)
assert old_drop in c, 'onFileDrop not found'
c = c.replace(old_drop, new_drop)
changes += 1

# 4. onFileSelect - handle multiple
old_sel = (
    'function onFileSelect(e) {\n'
    '  const files = e.target.files\n'
    '  if (files.length > 0) handleFile(files[0])\n'
    '}'
)
new_sel = (
    'function onFileSelect(e) {\n'
    '  const files = e.target.files\n'
    '  for (const f of files) handleFile(f)\n'
    '  fileInput.value.value = \'\'\n'
    '}'
)
assert old_sel in c, 'onFileSelect not found'
c = c.replace(old_sel, new_sel)
changes += 1

# 5. handleFile - support multiple files
old_hf = (
    'function handleFile(file) {\n'
    '  if (!validateFile(file)) {\n'
    '    showMessage(\'不支持的文件类型，请上传 .txt, .jpg, .jpeg, .png, .webp 文件\', \'error\')\n'
    '    return\n'
    '  }\n'
    '  uploadedFile.value = file\n'
    '  filePreview.value = null\n'
    '  const ext = file.name.split(\'.\').pop().toLowerCase()\n'
    '  if (ext === \'txt\') {\n'
    '    const reader = new FileReader()\n'
    '    reader.onload = (e) => { transcriptText.value = e.target.result; showMessage(\'文本文件读取成功\', \'success\'); currentStep.value = 1 }\n'
    '    reader.onerror = () => { showMessage(\'读取文本文件失败\', \'error\') }\n'
    '    reader.readAsText(file)\n'
    '  } else {\n'
    '    const reader = new FileReader()\n'
    '    reader.onload = (e) => { filePreview.value = e.target.result; transcriptText.value = `[图片上传: ${file.name}]`; showMessage(\'图片上传成功，请确认后生成\', \'success\'); currentStep.value = 1 }\n'
    '    reader.readAsDataURL(file)\n'
    '  }\n'
    '}'
)
new_hf = (
    'function getFileType(file) {\n'
    '  const ext = file.name.split(\'.\').pop().toLowerCase()\n'
    '  return [\'jpg\', \'jpeg\', \'png\', \'webp\'].includes(ext) ? \'image\' : \'text\'\n'
    '}\n'
    'function handleFile(file) {\n'
    '  if (!validateFile(file)) {\n'
    '    showMessage(\'不支持的文件类型，请上传 .txt, .jpg, .jpeg, .png, .webp 文件\', \'error\')\n'
    '    return\n'
    '  }\n'
    '  const ftype = getFileType(file)\n'
    '  if (ftype === \'text\') {\n'
    '    const reader = new FileReader()\n'
    '    reader.onload = (e) => {\n'
    '      transcriptText.value = transcriptText.value ? transcriptText.value + \'\\n\\n\' + e.target.result : e.target.result\n'
    '      uploadedFiles.value.push({ name: file.name, dataUrl: null, type: \'text\' })\n'
    '      showMessage(\'文本文件 \"\' + file.name + \'\" 读取成功\', \'success\')\n'
    '      currentStep.value = 1\n'
    '    }\n'
    '    reader.onerror = () => showMessage(\'读取文本文件失败\', \'error\')\n'
    '    reader.readAsText(file)\n'
    '  } else {\n'
    '    const reader = new FileReader()\n'
    '    reader.onload = (e) => {\n'
    '      uploadedFiles.value.push({ name: file.name, dataUrl: e.target.result, type: \'image\' })\n'
    '      showMessage(\'图片 \"\' + file.name + \'\" 上传成功\', \'success\')\n'
    '      currentStep.value = 1\n'
    '    }\n'
    '    reader.readAsDataURL(file)\n'
    '  }\n'
    '}'
)
assert old_hf in c, 'handleFile not found'
c = c.replace(old_hf, new_hf)
changes += 1

# 6. removeFile - takes index
old_rm = (
    'function removeFile() {\n'
    '  uploadedFile.value = null\n'
    '  filePreview.value = null\n'
    '  transcriptText.value = \'\'\n'
    '  currentStep.value = 1\n'
    '}'
)
new_rm = (
    'function removeFile(idx) {\n'
    '  const removed = uploadedFiles.value.splice(idx, 1)[0]\n'
    '  if (removed && removed.type === \'text\') {\n'
    '    transcriptText.value = \'\'\n'
    '  }\n'
    '  currentStep.value = 1\n'
    '}'
)
assert old_rm in c, 'removeFile not found'
c = c.replace(old_rm, new_rm)
changes += 1

# 7. update generateReview to send image data
old_gen = (
    '      input_type: uploadedFile.value && isImageFile.value ? \'screenshot\' : \'text\',\n'
    '      content: transcriptText.value,'
)
new_gen = (
    '      input_type: hasImages.value ? \'screenshot\' : \'text\',\n'
    '      content: transcriptText.value,\n'
    '      images: uploadedFiles.value.filter(f => f.type === \'image\').map(f => f.dataUrl),'
)
assert old_gen in c, 'generateReview not found'
c = c.replace(old_gen, new_gen)
changes += 1

# 8. Template: uploadedFile area (with multi-file list)
old_tpl1 = (
    '                <div v-if="!uploadedFile" class="space-y-2">\n'
    '                  <Upload class="h-8 w-8 mx-auto text-muted-foreground/40" />\n'
    '                  <p class="text-sm text-muted-foreground">点击或拖拽上传文件</p>\n'
    '                  <p class="text-xs text-muted-foreground/60">支持 .txt, .jpg, .jpeg, .png, .webp</p>\n'
    '                </div>\n'
    '                <div v-else class="flex items-center justify-between bg-muted/50 rounded-lg px-4 py-3">\n'
    '                  <div class="flex items-center gap-3">\n'
    '                    <FileText class="h-5 w-5 text-muted-foreground" />\n'
    '                    <span class="text-sm font-medium">{{ uploadedFile.name }}</span>\n'
    '                  </div>\n'
    '                  <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" @click.stop="removeFile">\n'
    '                    <X class="h-4 w-4 mr-1" />移除\n'
    '                  </Button>\n'
    '                </div>'
)
new_tpl1 = (
    '                <div v-if="!uploadedFiles.length" class="space-y-2">\n'
    '                  <Upload class="h-8 w-8 mx-auto text-muted-foreground/40" />\n'
    '                  <p class="text-sm text-muted-foreground">点击或拖拽上传文件（支持多选）</p>\n'
    '                  <p class="text-xs text-muted-foreground/60">支持 .txt, .jpg, .jpeg, .png, .webp</p>\n'
    '                </div>\n'
    '                <div v-else class="space-y-2">\n'
    '                  <div v-for="(f, idx) in uploadedFiles" :key="idx" class="flex items-center justify-between bg-muted/50 rounded-lg px-4 py-3">\n'
    '                    <div class="flex items-center gap-3">\n'
    '                      <Image v-if="f.type === \'image\'" class="h-5 w-5 text-muted-foreground" />\n'
    '                      <FileText v-else class="h-5 w-5 text-muted-foreground" />\n'
    '                      <span class="text-sm font-medium truncate max-w-[200px]">{{ f.name }}</span>\n'
    '                      <span class="text-xs text-muted-foreground/60">{{ f.type === \'image\' ? \'图片\' : \'文本\' }}</span>\n'
    '                    </div>\n'
    '                    <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" @click.stop="removeFile(idx)">\n'
    '                      <X class="h-4 w-4 mr-1" />移除\n'
    '                    </Button>\n'
    '                  </div>\n'
    '                </div>'
)
assert old_tpl1 in c, 'template1 not found'
c = c.replace(old_tpl1, new_tpl1)
changes += 1

# 9. Template: image preview area (multi-image)
old_tpl2 = (
    '            <div v-if="filePreview && isImageFile" class="w-[200px] shrink-0">\n'
    '              <img :src="filePreview" alt="预览" class="w-full rounded-xl border border-border" />\n'
    '            </div>'
)
new_tpl2 = (
    '            <div v-if="uploadedFiles.filter(f => f.type === \'image\').length" class="flex gap-2 flex-wrap">\n'
    '              <img v-for="(f, idx) in uploadedFiles.filter(f => f.type === \'image\')" :key="idx" :src="f.dataUrl" alt="预览" class="w-[120px] h-[80px] object-cover rounded-lg border border-border" />\n'
    '            </div>'
)
assert old_tpl2 in c, 'template2 not found'
c = c.replace(old_tpl2, new_tpl2)
changes += 1

# 10. Import Image icon
c = c.replace(
    "import { Search, RefreshCw, Upload, FileText, X, Check, ChevronDown, Plus, Sparkles, Loader2 } from '@lucide/vue'",
    "import { Search, RefreshCw, Upload, FileText, Image, X, Check, ChevronDown, Plus, Sparkles, Loader2 } from '@lucide/vue'"
)
changes += 1

with open('D:/智档/frontend/src/pages/ReviewPage.vue', 'w', encoding='utf-8') as f:
    f.write(c)

print(f'Done: {changes} changes applied')

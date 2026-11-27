export const MAX_RESEARCH_FILE_BYTES = 2 * 1024 * 1024;

export function validateFile(file: File) {
  if (file.size === 0 || file.size > MAX_RESEARCH_FILE_BYTES) {
    throw new Error('ファイルは空でない2 MiB以下のものを選んでください。');
  }
}

export function encodeDocument(file: File): Promise<string> {
  validateFile(file);
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error('ファイルを読み込めません。'));
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1]);
    reader.readAsDataURL(file);
  });
}

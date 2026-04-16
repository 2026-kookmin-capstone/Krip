import client from './client';

export interface UploadedImage {
  image_id: string;
  image_url: string;
}

export interface UploadImageResponse {
  images: UploadedImage[];
}

/**
 * 이미지 업로드 (최대 10개, 파일당 최대 10MB)
 * 허용 형식: image/jpeg, image/png, image/webp, image/gif
 */
export const uploadImages = async (files: File[]): Promise<UploadImageResponse> => {
  const formData = new FormData();
  files.forEach((file) => {
    formData.append('files', file);
  });

  const { data } = await client.post('/api/tripmate/images', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return data;
};

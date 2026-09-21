'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useSession } from 'next-auth/react';
import { api, getAccessToken, ApiError, NetworkError, UPLOAD_BASE_PATH } from '@/lib/api';

interface BodyPhotoResponse {
  body_photo_url: string | null;
}

export function useUploadBodyPhoto() {
  const queryClient = useQueryClient();
  const { data: session } = useSession();

  return useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append('image', file);

      const token = session?.accessToken || getAccessToken();
      const headers: Record<string, string> = {};
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      let response: Response;
      try {
        // Body photos are ordinary phone photos too - go straight to the backend,
        // bypassing the Next.js proxy route (Amplify's Lambda compute caps request
        // bodies at ~6MB), same as item image uploads in use-items.ts.
        response = await fetch(`${UPLOAD_BASE_PATH}/tryon/body-photo`, {
          method: 'POST',
          body: formData,
          credentials: 'include',
          headers,
        });
      } catch {
        if (!navigator.onLine) {
          throw new NetworkError('You appear to be offline. Please check your connection.');
        }
        throw new NetworkError('Unable to connect to server. Please try again.');
      }

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new ApiError(data.detail || 'Failed to upload body photo', response.status, data);
      }

      return response.json() as Promise<BodyPhotoResponse>;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user-profile'] });
    },
  });
}

export function useDeleteBodyPhoto() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api.delete<void>('/tryon/body-photo'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user-profile'] });
    },
  });
}

interface GenerateTryOnParams {
  itemIds: string[];
  comments?: string[];
}

export function useGenerateTryOn() {
  const { data: session } = useSession();

  return useMutation({
    // Always sends item_ids (never the previously generated image) so every
    // regeneration - comments included - starts fresh from the original body photo
    // and garment photos. Feeding a prior result back in would compound edits and
    // drift the person's face/body a little more each time.
    mutationFn: async ({ itemIds, comments }: GenerateTryOnParams) => {
      const token = session?.accessToken || getAccessToken();
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      let response: Response;
      try {
        // The response here is a generated image (can run to a few MB) - same Lambda
        // payload-size reasoning as the upload above applies to the way back.
        response = await fetch(`${UPLOAD_BASE_PATH}/tryon/generate`, {
          method: 'POST',
          body: JSON.stringify({ item_ids: itemIds, comments: comments ?? [] }),
          credentials: 'include',
          headers,
        });
      } catch {
        if (!navigator.onLine) {
          throw new NetworkError('You appear to be offline. Please check your connection.');
        }
        throw new NetworkError('Unable to connect to server. Please try again.');
      }

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new ApiError(data.detail || 'Failed to generate try-on', response.status, data);
      }

      const blob = await response.blob();
      return URL.createObjectURL(blob);
    },
  });
}

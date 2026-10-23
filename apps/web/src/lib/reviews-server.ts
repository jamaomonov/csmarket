import type { PublicReviews } from "@/lib/reviews";

import { apiGet } from "@/lib/server-api";

/** The first page of published reviews as the API serves it now (5-minute data cache); `null`
 * when it cannot say. */
export async function fetchPublicReviews(locale: string): Promise<PublicReviews | null> {
  try {
    return await apiGet<PublicReviews>(`/reviews?locale=${locale}`, {
      revalidate: 300,
      tags: ["reviews"],
    });
  } catch {
    return null;
  }
}

/** Whether the public `/reviews` page is on; off when the API cannot say. */
export async function reviewsPublic(): Promise<boolean> {
  return (await fetchPublicReviews("ru"))?.enabled === true;
}

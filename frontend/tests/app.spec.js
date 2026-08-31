const { test, expect } = require('@playwright/test');

const catalog = {
  datasets: [
    { name: 'majors', format: 'csv', description: 'Направления', available: true, size_bytes: 128 },
    { name: 'study_plan_disciplines', format: 'jsonl', description: 'Дисциплины', available: true, size_bytes: 256 },
  ],
  quality: { parse: { verification: { passed: true } } },
};

test.beforeEach(async ({ page }) => {
  await page.route('http://127.0.0.1:8000/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === '/health') {
      await route.fulfill({ json: { status: 'ok', service: 'test', version: '1.0.0', dataset_ready: true, quality_passed: true } });
    } else if (pathname === '/api/v1/catalog') {
      await route.fulfill({ json: catalog });
    } else if (pathname === '/api/v1/majors') {
      await route.fulfill({ json: { dataset: 'majors', items: [{ slug: 'ibm3', code: '38.03.05', name: 'Бизнес-информатика', faculty_name: 'Факультет', program_count: 1 }], offset: 0, limit: 500, total: 1, has_more: false } });
    } else if (pathname === '/api/v1/programs') {
      await route.fulfill({ json: { dataset: 'educational_programs', items: [{ id: 'program-1', code: 'P-1', name: 'Бизнес-информатика', department_name: 'Кафедра' }], offset: 0, limit: 500, total: 1, has_more: false } });
    } else if (pathname === '/api/v1/study-plans/documents') {
      await route.fulfill({ json: { dataset: 'study_plan_documents', items: [{ document_id: 'document-1', local_path: 'study_plans/plan.pdf', status: 'ok', table_count: 1, row_count: 2 }], offset: 0, limit: 500, total: 1, has_more: false } });
    } else if (pathname.endsWith('/rows')) {
      await route.fulfill({ json: { dataset: 'study_plan_disciplines', items: [{ id: 'discipline-1', code: '1', name: 'Математика', department: 'Кафедра' }], offset: 0, limit: 500, total: 1, has_more: false } });
    } else {
      await route.fulfill({ status: 404, json: { detail: 'not found' } });
    }
  });
});

test('loads the console and navigates the core catalog views', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Операционный обзор' })).toBeVisible();
  await expect(page.getByTestId('api-status')).toContainText('API online');
  await expect(page.getByText('Бизнес-информатика').first()).toBeVisible();

  await page.getByRole('button', { name: 'Направления' }).click();
  await expect(page.getByTestId('app-view').getByRole('heading', { name: 'Направления подготовки' })).toBeVisible();
  await page.getByRole('searchbox', { name: 'Поиск направления' }).fill('бизнес');
  await expect(page.getByText('Бизнес-информатика').first()).toBeVisible();

  await page.getByRole('button', { name: 'Программы' }).click();
  await expect(page.getByTestId('app-view').getByRole('heading', { name: 'Образовательные программы' })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'Кафедра' })).toBeVisible();

  await page.getByRole('button', { name: 'Каталог данных' }).click();
  await expect(page.getByTestId('app-view').getByRole('heading', { name: 'Каталог данных' })).toBeVisible();
  await expect(page.getByText('study_plan_disciplines')).toBeVisible();
});

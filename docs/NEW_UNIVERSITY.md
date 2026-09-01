# Подключение нового университета

Новый университет подключается как изолированный модуль. После изменения
платформенного контракта добавляется только каталог университета и одна строка
в composition root (`backend/src/university_data/registry.py`).

```text
backend/src/university_data/universities/<id>/
├── manifest.yaml
├── module.py
├── providers/
├── mappings/
├── resolvers/
└── tests/
```

Модуль реализует `UniversityModule` из
`university_data.core.plugin`:

```python
class NewUniversityModule:
    def manifest(self) -> UniversityManifest: ...
    def providers(self, options=None) -> ProviderSet: ...
    def resolvers(self) -> ResolverRegistry: ...
    def operations(self) -> UniversityOperations: ...
```

Каждый provider объявляет capability, возвращает соответствующий typed
`Source*` DTO и сохраняет `SourceProvenance`. Для частичного, но допустимого
источника используется `ProviderResult(records=..., complete=False,
warnings=..., gaps=...)`, а в manifest у capability задаётся
`allow_partial: true`. Без этого новый snapshot не публикуется.

Capability, отсутствующая у университета, не включается в manifest. Core не
создаёт для неё пустые canonical datasets, API отвечает
`404 capability_unavailable`, а ссылки на отсутствующие сущности сохраняются
в `extensions.<id>.unresolved_references` без synthetic Ontology edge.

Пример регистрации:

```python
REGISTRY = UniversityRegistry((
    BmstuModule(),
    HseModule(),
    NewUniversityModule(),
))
```

Единые contract tests должны проверять тип DTO, непустой стабильный
`source_key`, provenance/raw lineage, уникальность source keys и canonical IDs,
а также сохранение предыдущего active snapshot при ошибке provider.


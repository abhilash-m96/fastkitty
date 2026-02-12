from pydantic import BaseModel, Field


class ConfigProviderConnectionData(BaseModel):
    pass


class FileConnectionData(ConfigProviderConnectionData):
    """Schema for file-based config provider connection data."""

    file_path: str = Field(..., description="Path to the JSON configuration file")

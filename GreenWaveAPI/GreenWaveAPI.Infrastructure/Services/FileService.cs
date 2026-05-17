using GreenWaveAPI.Application.DTOs;
using GreenWaveAPI.Application.Interfaces;
using System.Text.Json;

namespace GreenWaveAPI.Infrastructure.Services;

public class FileService : IFileService
{
    public async Task SaveJsonAsync(SumoTrafficDto dto)
    {
        var rootFolder = Path.Combine(Directory.GetCurrentDirectory(), "TrafficLogs");

        if (!Directory.Exists(rootFolder))
            Directory.CreateDirectory(rootFolder);

        var junctionFolder = Path.Combine(rootFolder, $"Junction_{dto.JunctionId}");

        if (!Directory.Exists(junctionFolder))
            Directory.CreateDirectory(junctionFolder);

        var fileName = $"{dto.ReceivedTime:yyyy-MM-dd_HH-mm-ss}.json";

        var filePath = Path.Combine(junctionFolder, fileName);

        var json = System.Text.Json.JsonSerializer.Serialize(dto, new System.Text.Json.JsonSerializerOptions
        {
            WriteIndented = true
        });

        await File.WriteAllTextAsync(filePath, json);
    }
}

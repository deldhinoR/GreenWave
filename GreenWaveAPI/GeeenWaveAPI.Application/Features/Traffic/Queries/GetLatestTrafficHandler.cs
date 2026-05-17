using MediatR;
using GreenWaveAPI.Application.DTOs;
using GreenWaveAPI.Application.Features.Traffic.Queries;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace GreenWaveAPI.Application.Features.Traffic.Handlers
{
    public class GetLatestTrafficHandler : IRequestHandler<GetLatestTrafficQuery, SumoTrafficDto>
    {
        public async Task<SumoTrafficDto> Handle(GetLatestTrafficQuery request, CancellationToken cancellationToken)
        {
            // Junction klasörü
            var dir = Path.Combine(Directory.GetCurrentDirectory(), "TrafficLogs", $"Junction_{request.JunctionId}");
            if (!Directory.Exists(dir))
                return null;

            // Son kaydedilen dosya
            var lastFile = new DirectoryInfo(dir)
                            .GetFiles()
                            .OrderByDescending(f => f.CreationTime)
                            .FirstOrDefault();

            if (lastFile == null)
                return null; // Dosya yok → NotFound

            // Dosyayı oku
            var json = await File.ReadAllTextAsync(lastFile.FullName, cancellationToken);
            var trafficData = JsonSerializer.Deserialize<SumoTrafficDto>(json);

            return trafficData;
        }
    }
}
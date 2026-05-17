using MediatR;
using Microsoft.AspNetCore.Mvc;
using GreenWaveAPI.Application.Features.Traffic.Commands;

namespace GreenWaveAPI.Controllers;

[ApiController]
[Route("api/[controller]")]
public class TrafficController : ControllerBase
{
    private readonly IMediator _mediator;

    public TrafficController(IMediator mediator)
    {
        _mediator = mediator;
    }

    /// <summary>
    /// Receives traffic data from image processing, saves it to file, and sends it to SUMO.
    /// </summary>
    [HttpPost]
    public async Task<IActionResult> CreateTraffic([FromBody] CreateTrafficCommandRequest request)
    {
        if (request == null || request.Roads == null || !request.Roads.Any())
        {
            return BadRequest("Invalid traffic data received.");
        }

        try
        {
            // MediatR handler çağrılıyor
            await _mediator.Send(request);

            // Açıklayıcı bir mesaj dönebiliriz
            return Ok(new
            {
                Status = "Success",
                Message = "Traffic data saved and sent to SUMO."
            });
        }
        catch (Exception ex)
        {
            // Hata yönetimi
            return StatusCode(500, new
            {
                Status = "Error",
                Message = "Failed to process traffic data.",
                Details = ex.Message
            });
        }
    }
}